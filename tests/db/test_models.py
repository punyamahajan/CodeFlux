from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.db.models import (
    ArenaRun,
    CreditLedger,
    LimitRequest,
    Organization,
    PlatformKey,
    ProviderCredential,
    RequestTrace,
    Route,
    Session,
    SessionMessage,
    User,
    generate_id,
)


def test_id_generator_prefixes():
    for prefix in ["org", "usr", "crd", "key", "rte", "req", "led", "trc", "ses", "msg", "arn"]:
        generated = generate_id(prefix)
        assert generated.startswith(f"{prefix}_")
        assert len(generated) > len(prefix) + 1


@pytest.mark.asyncio
async def test_all_models_persist_and_link_by_org(db_session: AsyncSession):
    # 1. Organization
    org = Organization(name="Acme Corp")
    db_session.add(org)
    await db_session.flush()
    assert org.id.startswith("org_")
    assert org.created_at is not None

    # 2. User
    user = User(
        org_id=org.id,
        email="admin@acme.com",
        password_hash="argon2_hashed_secret",
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()
    assert user.id.startswith("usr_")
    assert user.org_id == org.id

    # 3. ProviderCredential
    cred = ProviderCredential(
        org_id=org.id,
        provider="openai",
        key_hint="1234",
        encrypted_key="gAAAAAB...",
        enabled=True,
    )
    db_session.add(cred)
    await db_session.flush()
    assert cred.id.startswith("crd_")
    assert cred.org_id == org.id

    # 4. PlatformKey
    key = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Developer Key",
        key_prefix="ok_live_abc123",
        key_digest="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        credit_limit_micro=10_000_000,  # 10 USD
        credit_remaining_micro=10_000_000,
        rpm_limit=120,
        allowed_routes=["fast", "smart"],
    )
    db_session.add(key)
    await db_session.flush()
    assert key.id.startswith("key_")
    assert key.credit_limit_micro == 10_000_000
    assert key.allowed_routes == ["fast", "smart"]

    # 5. Route
    route = Route(
        org_id=org.id,
        alias="smart",
        strategy="priority",
        task_tag="code",
        candidates=[{"provider": "openai", "model": "gpt-4o"}],
    )
    db_session.add(route)
    await db_session.flush()
    assert route.id.startswith("rte_")
    assert route.candidates[0]["provider"] == "openai"

    # 6. LimitRequest
    req = LimitRequest(
        org_id=org.id,
        key_id=key.id,
        user_id=user.id,
        requested_credit_micro=50_000_000,
        status="pending",
        reason="Need quota for staging demo",
    )
    db_session.add(req)
    await db_session.flush()
    assert req.id.startswith("req_")
    assert req.requested_credit_micro == 50_000_000

    # 7. CreditLedger
    ledger = CreditLedger(
        org_id=org.id,
        key_id=key.id,
        amount_micro=-15_000,
        balance_after_micro=9_985_000,
        reason="usage_deduction",
        trace_id="trc_test123",
    )
    db_session.add(ledger)
    await db_session.flush()
    assert ledger.id.startswith("led_")
    assert ledger.balance_after_micro == 9_985_000

    # 8. RequestTrace
    trace = RequestTrace(
        org_id=org.id,
        key_id=key.id,
        provider="openai",
        model="gpt-4o",
        status_code=200,
        latency_ms=350,
        prompt_tokens=100,
        completion_tokens=50,
        cost_micro=15_000,
        facts={"attempts": [{"provider": "openai", "status": "succeeded"}]},
    )
    db_session.add(trace)
    await db_session.flush()
    assert trace.id.startswith("trc_")
    assert trace.facts["attempts"][0]["provider"] == "openai"

    # 9. Session
    sess = Session(org_id=org.id, key_id=key.id)
    db_session.add(sess)
    await db_session.flush()
    assert sess.id.startswith("ses_")

    # 10. SessionMessage
    msg = SessionMessage(
        org_id=org.id,
        session_id=sess.id,
        role="user",
        content="Hello world",
    )
    db_session.add(msg)
    await db_session.flush()
    assert msg.id.startswith("msg_")
    assert msg.content == "Hello world"

    # 11. ArenaRun
    arena = ArenaRun(
        org_id=org.id,
        key_id=key.id,
        kind="compare",
        facts={"models": ["gpt-4o", "gemini-2.0-flash"], "winner": "gpt-4o"},
    )
    db_session.add(arena)
    await db_session.flush()
    assert arena.id.startswith("arn_")
    assert arena.facts["winner"] == "gpt-4o"


@pytest.mark.asyncio
async def test_unique_user_email_per_org(db_session: AsyncSession):
    org = Organization(name="Test Org")
    db_session.add(org)
    await db_session.flush()

    user1 = User(org_id=org.id, email="alice@test.com", password_hash="hash1")
    db_session.add(user1)
    await db_session.flush()

    user2 = User(org_id=org.id, email="alice@test.com", password_hash="hash2")
    db_session.add(user2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_biginteger_micro_usd_precision(db_session: AsyncSession):
    org = Organization(name="Finance Org")
    db_session.add(org)
    await db_session.flush()

    user = User(org_id=org.id, email="finance@org.com", password_hash="hash")
    db_session.add(user)
    await db_session.flush()

    # Test large integer: $1,000,000.00 = 1,000,000,000,000 micro-USD
    huge_amount = 1_000_000_000_000
    key = PlatformKey(
        org_id=org.id,
        user_id=user.id,
        name="Enterprise Key",
        key_prefix="ok_live_ent",
        key_digest="digest_enterprise",
        credit_limit_micro=huge_amount,
        credit_remaining_micro=huge_amount,
        allowed_routes=["*"],
    )
    db_session.add(key)
    await db_session.flush()

    loaded = await db_session.scalar(select(PlatformKey).where(PlatformKey.id == key.id))
    assert loaded is not None
    assert loaded.credit_limit_micro == huge_amount
    assert loaded.credit_remaining_micro == huge_amount


@pytest.mark.asyncio
async def test_per_test_rollback_isolation_step_1(db_session: AsyncSession):
    # Insert an organization with a specific marker
    org = Organization(id="org_isolation_check", name="Isolation Marker")
    db_session.add(org)
    await db_session.commit()
    res = await db_session.scalar(
        select(Organization).where(Organization.id == "org_isolation_check")
    )
    assert res is not None


@pytest.mark.asyncio
async def test_per_test_rollback_isolation_step_2(db_session: AsyncSession):
    # Verify the marker from step 1 was rolled back and is NOT present
    res = await db_session.scalar(
        select(Organization).where(Organization.id == "org_isolation_check")
    )
    assert res is None
