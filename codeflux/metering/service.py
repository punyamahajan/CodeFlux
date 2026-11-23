from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.db.models import CreditLedger, Organization, PlatformKey, RequestTrace
from codeflux.metering.pricing import CostResult, compute_cost
from codeflux.schemas import Usage

logger = logging.getLogger("codeflux.metering")


async def record_usage_and_trace(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: str,
    key_id: str | None,
    provider: str | None,
    model: str | None,
    status_code: int,
    latency_ms: int,
    prompt_tokens: int,
    completion_tokens: int,
    trace_id: str | None = None,
    facts: dict[str, Any] | None = None,
) -> tuple[int | None, CostResult, RequestTrace | None]:
    """Atomically decrement platform key credits, insert credit ledger entry, and persist request trace.

    All database mutations execute in a single atomic transaction.
    """
    tid = trace_id or f"trc_{uuid.uuid4().hex[:28]}"
    model_name = model or "default"
    usage = Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )
    cost = compute_cost(usage, model_name)

    balance_after: int | None = None

    try:
        async with session_factory() as session:
            # Check org exists before attempting foreign-key constrained inserts
            org_exists = await session.get(Organization, org_id)
            if not org_exists:
                return None, cost, None

            # 1. Atomically decrement key's credits if a platform key is associated
            actual_key_id = key_id
            if actual_key_id:
                stmt = (
                    update(PlatformKey)
                    .where(PlatformKey.id == actual_key_id)
                    .values(
                        credit_remaining_micro=PlatformKey.credit_remaining_micro
                        - cost.charged_micro,
                        last_used_at=datetime.now(UTC),
                    )
                    .returning(PlatformKey.credit_remaining_micro)
                )
                res = await session.execute(stmt)
                balance_after = res.scalar_one_or_none()

                if balance_after is not None:
                    # 2. Insert CreditLedger row
                    ledger = CreditLedger(
                        org_id=org_id,
                        key_id=actual_key_id,
                        amount_micro=-cost.charged_micro,
                        balance_after_micro=balance_after,
                        reason="usage_deduction",
                        trace_id=tid,
                    )
                    session.add(ledger)
                else:
                    actual_key_id = None

            # 3. Build trace facts compliant with the Explain contract
            trace_facts = {
                "schema_version": 1,
                "pricing_version": cost.price_version,
                "charged_cost_micro": cost.charged_micro,
                "list_cost_micro": cost.list_micro,
                "savings_micro": cost.savings_micro,
                "is_estimate": True,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "model": model_name,
                "provider": provider,
                "latency_ms": latency_ms,
                "status_code": status_code,
            }
            if facts:
                trace_facts.update(facts)

            # 4. Insert RequestTrace
            trace = RequestTrace(
                id=tid,
                org_id=org_id,
                key_id=actual_key_id,
                provider=provider,
                model=model_name,
                status_code=status_code,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_micro=cost.charged_micro,
                facts=trace_facts,
            )
            session.add(trace)

            await session.commit()
            return balance_after, cost, trace
    except SQLAlchemyError as exc:
        logger.warning("Failed to record usage and trace: %s", exc)
        return None, cost, None
