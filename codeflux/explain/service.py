"""Explain service: load facts, validate, render, optionally narrate."""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.db.models import ArenaRun, RequestTrace
from codeflux.explain.facts import parse_facts
from codeflux.explain.templates import render

logger = logging.getLogger("codeflux.explain")

# Numbers that appear in narration replies — anything that looks like an
# integer or decimal (possibly with a leading $ or %).
_NUMBER_RE = re.compile(r"\$?\d+(?:[.,]\d+)*")

# Key cached inside the facts JSON for accepted narrations.
_NARRATION_CACHE_KEY = "_narration"


async def explain_trace(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    trace_id: str,
    org_id: str,
    kind: str = "trace",
) -> dict[str, Any] | None:
    """Load a RequestTrace by id, validate its facts, return rendered explanation.

    Returns *None* if the trace does not exist or belongs to a different org.
    """
    async with session_factory() as session:
        stmt = select(RequestTrace).where(
            RequestTrace.id == trace_id, RequestTrace.org_id == org_id
        )
        result = await session.execute(stmt)
        trace = result.scalar_one_or_none()
        if trace is None:
            return None
        raw: dict[str, Any] = dict(trace.facts or {})

    # For cost kind we extract cost sub-fields from the same facts blob.
    if kind == "cost":
        raw.setdefault("schema_version", raw.get("schema_version", 1))
    if kind == "blocked":
        # blocked traces store their block_reason at top level;
        # synthesise a BlockedFacts-compatible dict
        if "reason" not in raw:
            raw["reason"] = raw.get("block_reason", "unknown")
        if "detail" not in raw:
            raw["detail"] = raw.get("block_reason", "unknown")

    try:
        facts_obj = parse_facts(kind, raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Facts validation failed for trace %s kind %s: %s", trace_id, kind, exc)
        return None

    return render(kind, facts_obj)


async def explain_arena(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    run_id: str,
    org_id: str,
    kind: str,
) -> dict[str, Any] | None:
    """Load an ArenaRun by id, validate its facts, return rendered explanation."""
    async with session_factory() as session:
        stmt = select(ArenaRun).where(ArenaRun.id == run_id, ArenaRun.org_id == org_id)
        result = await session.execute(stmt)
        run = result.scalar_one_or_none()
        if run is None:
            return None
        raw: dict[str, Any] = dict(run.facts or {})

    try:
        facts_obj = parse_facts(kind, raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Facts validation failed for arena run %s kind %s: %s", run_id, kind, exc)
        return None

    return render(kind, facts_obj)


def _extract_numbers(text: str) -> set[str]:
    """Return every numeric token found in *text*, stripping currency signs."""
    matches = _NUMBER_RE.findall(text)
    return {m.lstrip("$") for m in matches if m.lstrip("$")}


def _numbers_in_facts(raw: dict[str, Any]) -> set[str]:
    """Collect all number-like strings from the facts JSON (recursively)."""
    nums: set[str] = set()
    stack: list[Any] = [raw]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, (int, float)):
            # Format integers and decimals consistently with the regex
            nums.add(str(item))
            # Also add with comma separators for large numbers
            if isinstance(item, int) and item >= 1000:
                nums.add(f"{item:,}")
    return nums


def _narration_guard(reply: str, raw_facts: dict[str, Any]) -> bool:
    """Return True if the narration reply is acceptable (no invented numbers)."""
    reply_numbers = _extract_numbers(reply)
    if not reply_numbers:
        return True  # no numbers at all — fine
    allowed = _numbers_in_facts(raw_facts)
    # Allow $ amounts derived from micro-USD values
    # e.g. micro=1500000 → $1.500000; also the raw micro value
    for val in list(allowed):
        try:
            micro = int(val.replace(",", ""))
            # dollar representation: micro / 1_000_000
            dollar = f"{micro / 1_000_000:.6f}"
            allowed.add(dollar)
            allowed.add(dollar.rstrip("0").rstrip("."))
            # also the rounded forms
            for dp in range(7):
                allowed.add(f"{micro / 1_000_000:.{dp}f}")
        except (ValueError, OverflowError):
            pass
    # Any number in the reply that is NOT in the allowed set is invented
    invented = reply_numbers - allowed
    if invented:
        logger.warning("Narration guard: invented numbers %s", invented)
        return False
    return True


async def narrate(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    record_id: str,
    org_id: str,
    kind: str,
    is_arena: bool,
    narration_client: httpx.AsyncClient,
    narration_url: str,
    narration_key: str,
    narration_model: str = "gpt-4o-mini",
) -> dict[str, Any]:
    """Generate (or return cached) AI narration for an explain record.

    Sends only the facts JSON to the model.  Validates that the reply contains
    no numbers absent from the facts.  Returns the deterministic text on guard
    failure or any error.
    """
    # 1. Load raw facts
    async with session_factory() as session:
        if is_arena:
            stmt = select(ArenaRun).where(ArenaRun.id == record_id, ArenaRun.org_id == org_id)
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
        else:
            stmt2 = select(RequestTrace).where(
                RequestTrace.id == record_id, RequestTrace.org_id == org_id
            )
            result2 = await session.execute(stmt2)
            row = result2.scalar_one_or_none()

        if row is None:
            return {"error": "not_found"}

        raw: dict[str, Any] = dict(row.facts or {})

    # 2. Return cached narration if present
    if _NARRATION_CACHE_KEY in raw:
        return {"narration": raw[_NARRATION_CACHE_KEY], "cached": True}

    # 3. Validate facts
    try:
        facts_obj = parse_facts(kind, raw)
    except (ValueError, TypeError) as exc:
        logger.warning("Narration: facts validation failed: %s", exc)
        return {"narration": str(exc), "guard": "validation_error"}

    deterministic = render(kind, facts_obj)
    facts_json_str = facts_obj.model_dump_json(indent=2)

    system_prompt = (
        "You are a helpful assistant explaining an AI gateway decision. "
        "You will receive a JSON object of facts. "
        "Write a concise plain-English explanation (3-5 sentences). "
        "IMPORTANT: Do not introduce any numbers that are not present in the facts JSON. "
        "Do not round, estimate, or extrapolate numbers."
    )
    user_prompt = f"Explain the following facts in plain English:\n\n{facts_json_str}"

    # 4. Call the AI
    try:
        response = await narration_client.post(
            narration_url,
            headers={"Authorization": f"Bearer {narration_key}"},
            json={
                "model": narration_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": 300,
            },
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        reply_text: str = data["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError) as exc:
        logger.warning("Narration AI call failed: %s", exc)
        return {
            "narration": deterministic["headline"],
            "bullets": deterministic["bullets"],
            "guard": "ai_error",
        }

    # 5. Guard: reject if invented numbers detected
    if not _narration_guard(reply_text, raw):
        return {
            "narration": deterministic["headline"],
            "bullets": deterministic["bullets"],
            "guard": "rejected_invented_numbers",
        }

    # 6. Cache accepted narration back into facts
    raw[_NARRATION_CACHE_KEY] = reply_text
    async with session_factory() as session:
        if is_arena:
            stmt3 = select(ArenaRun).where(ArenaRun.id == record_id, ArenaRun.org_id == org_id)
            result3 = await session.execute(stmt3)
            row3 = result3.scalar_one_or_none()
            if row3 is not None:
                row3.facts = raw
                await session.commit()
        else:
            stmt4 = select(RequestTrace).where(
                RequestTrace.id == record_id, RequestTrace.org_id == org_id
            )
            result4 = await session.execute(stmt4)
            row4 = result4.scalar_one_or_none()
            if row4 is not None:
                row4.facts = raw
                await session.commit()

    return {"narration": reply_text, "cached": False}
