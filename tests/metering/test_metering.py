from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from codeflux.app import create_app
from codeflux.db.models import CreditLedger, Organization, PlatformKey, User
from codeflux.db.session import get_db_session
from codeflux.metering.service import record_usage_and_trace
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.settings import Settings


@pytest.fixture
async def metering_fixture(
    db_session: AsyncSession,
) -> tuple[Organization, User, PlatformKey, str]:
    settings = Settings(env="test")
    org = Organization(name="Metering Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        org_id=org.id,
        email="metering@example.com",
        password_hash="pw",
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_platform_key()
    digest = hash_platform_key(raw_key, settings.key_hmac_secret)
    initial_limit = 10_000_000  # $10.00
    key = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Metering Key",
        key_prefix=raw_key[:16],
        key_digest=digest,
        credit_limit_micro=initial_limit,
        credit_remaining_micro=initial_limit,
        rpm_limit=100,
    )
    db_session.add(key)
    await db_session.flush()

    # Initial grant ledger row
    init_ledger = CreditLedger(
        org_id=org.id,
        key_id=key.id,
        amount_micro=initial_limit,
        balance_after_micro=initial_limit,
        reason="initial_grant",
    )
    db_session.add(init_ledger)
    await db_session.flush()

    return org, user, key, raw_key


@pytest.mark.asyncio
async def test_record_usage_and_trace_deduction(
    session_factory: async_sessionmaker[AsyncSession],
    metering_fixture: tuple[Organization, User, PlatformKey, str],
):
    org, _, key, _ = metering_fixture

    # Execute one deduction
    balance_after, cost, trace = await record_usage_and_trace(
        session_factory,
        org_id=org.id,
        key_id=key.id,
        provider="openai",
        model="gpt-4o-mini",
        status_code=200,
        latency_ms=120,
        prompt_tokens=1000,
        completion_tokens=500,
    )

    # Cost of gpt-4o-mini: 1000*0.15/1M (150) + 500*0.60/1M (300) = 450 micro-USD
    assert cost.charged_micro == 450
    assert balance_after == 10_000_000 - 450
    assert trace.cost_micro == 450
    assert trace.facts["schema_version"] == 1
    assert trace.facts["charged_cost_micro"] == 450
    assert trace.facts["is_estimate"] is True

    # Verify database state
    async with session_factory() as session:
        refreshed_key = await session.get(PlatformKey, key.id)
        assert refreshed_key is not None
        assert refreshed_key.credit_remaining_micro == 10_000_000 - 450

        # Verify CreditLedger
        ledgers = (
            (
                await session.execute(
                    select(CreditLedger)
                    .where(CreditLedger.key_id == key.id)
                    .order_by(CreditLedger.created_at)
                )
            )
            .scalars()
            .all()
        )

        assert len(ledgers) == 2
        assert ledgers[1].amount_micro == -450
        assert ledgers[1].balance_after_micro == 10_000_000 - 450
        assert ledgers[1].reason == "usage_deduction"
        assert ledgers[1].trace_id == trace.id


@pytest.mark.asyncio
async def test_concurrent_requests_no_lost_update(engine: AsyncEngine):
    pool_factory = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(env="test")

    # Setup org, user, key directly committed in engine for multi-connection isolation
    async with pool_factory() as s:
        org = Organization(name="Concurrent Test Org")
        s.add(org)
        await s.flush()
        user = User(org_id=org.id, email="concurrent@test.com", password_hash="pw", role="member")
        s.add(user)
        await s.flush()
        raw_key = generate_platform_key()
        digest = hash_platform_key(raw_key, settings.key_hmac_secret)
        initial_limit = 10_000_000
        key = PlatformKey(
            org_id=org.id,
            user_id=user.id,
            name="Concurrent Key",
            key_prefix=raw_key[:16],
            key_digest=digest,
            credit_limit_micro=initial_limit,
            credit_remaining_micro=initial_limit,
            rpm_limit=100,
        )
        s.add(key)
        await s.flush()

        init_ledger = CreditLedger(
            org_id=org.id,
            key_id=key.id,
            amount_micro=initial_limit,
            balance_after_micro=initial_limit,
            reason="initial_grant",
        )
        s.add(init_ledger)
        await s.commit()

        key_id = key.id
        org_id = org.id

    # Fire two concurrent deductions on the same platform key on separate connections
    # Request 1: 10,000 prompt tokens on gpt-4o = 25,000 micro-USD
    # Request 2: 20,000 prompt tokens on gpt-4o = 50,000 micro-USD
    t1 = record_usage_and_trace(
        pool_factory,
        org_id=org_id,
        key_id=key_id,
        provider="openai",
        model="gpt-4o",
        status_code=200,
        latency_ms=200,
        prompt_tokens=10_000,
        completion_tokens=0,
    )
    t2 = record_usage_and_trace(
        pool_factory,
        org_id=org_id,
        key_id=key_id,
        provider="openai",
        model="gpt-4o",
        status_code=200,
        latency_ms=210,
        prompt_tokens=20_000,
        completion_tokens=0,
    )

    results = await asyncio.gather(t1, t2)
    _b1, cost1, _ = results[0]
    _b2, cost2, _ = results[1]

    assert cost1.charged_micro == 25_000
    assert cost2.charged_micro == 50_000

    # Total deduction must be exactly 75,000 with NO lost update
    expected_remaining = 10_000_000 - 75_000
    async with pool_factory() as s:
        refreshed_key = await s.get(PlatformKey, key_id)
        assert refreshed_key is not None
        assert refreshed_key.credit_remaining_micro == expected_remaining

        # Invariant check:
        # 1. Total usage deductions sum to limit minus remaining credits
        usage_ledgers = (
            (
                await s.execute(
                    select(CreditLedger).where(
                        CreditLedger.key_id == key_id, CreditLedger.reason == "usage_deduction"
                    )
                )
            )
            .scalars()
            .all()
        )

        total_deductions = sum(abs(l.amount_micro) for l in usage_ledgers)
        assert total_deductions == 75_000
        assert (
            total_deductions
            == refreshed_key.credit_limit_micro - refreshed_key.credit_remaining_micro
        )

        # 2. All ledger entries (initial grant + deductions) sum to remaining credits
        all_ledgers = (
            (await s.execute(select(CreditLedger).where(CreditLedger.key_id == key_id)))
            .scalars()
            .all()
        )
        assert sum(l.amount_micro for l in all_ledgers) == refreshed_key.credit_remaining_micro


@pytest.mark.asyncio
async def test_key_at_zero_credits_refused_with_clear_error(
    db_session: AsyncSession, tmp_path: Path
):
    # Setup test app and key with zero credits
    config_path = tmp_path / "routes.yaml"
    config_path.write_text(
        json.dumps(
            {
                "routes": {
                    "default": {
                        "candidates": [
                            {"provider": "openai", "model": "gpt-4o-mini", "timeout_seconds": 10.0}
                        ]
                    }
                },
                "default_route": "default",
            }
        )
    )

    settings = Settings(env="test", config_path=config_path)
    app = create_app(settings)

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    org = Organization(name="Zero Credit Org")
    db_session.add(org)
    await db_session.flush()

    user = User(org_id=org.id, email="zero@test.com", password_hash="pw", role="member")
    db_session.add(user)
    await db_session.flush()

    raw_key = generate_platform_key()
    digest = hash_platform_key(raw_key, settings.key_hmac_secret)
    zero_key = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Zero Key",
        key_prefix=raw_key[:16],
        key_digest=digest,
        credit_limit_micro=10_000_000,
        credit_remaining_micro=0,  # Zero credits!
        rpm_limit=60,
    )
    db_session.add(zero_key)
    await db_session.flush()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {raw_key}"},
            json={"model": "default", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 429
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "insufficient_credits"
        assert data["error"]["type"] == "insufficient_quota"
        assert "insufficient credits" in data["error"]["message"].lower()
