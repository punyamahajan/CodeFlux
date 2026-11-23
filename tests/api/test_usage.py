from __future__ import annotations

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
from codeflux.db.models import CreditLedger, Organization, PlatformKey, RequestTrace, User
from codeflux.db.session import get_db_session
from codeflux.security.crypto import generate_platform_key, hash_platform_key
from codeflux.security.passwords import hash_password
from codeflux.security.tokens import create_access_token
from codeflux.settings import Settings


@pytest.fixture
async def usage_test_data(db_session: AsyncSession) -> dict[str, str]:
    settings = Settings(env="test")

    # 1. Org 1: Admin and Member
    org1 = Organization(name="Usage Org 1")
    db_session.add(org1)
    await db_session.flush()

    admin = User(
        org_id=org1.id,
        email="admin@usage.com",
        password_hash=hash_password("adminpw123"),
        role="admin",
    )
    member = User(
        org_id=org1.id,
        email="member@usage.com",
        password_hash=hash_password("memberpw123"),
        role="member",
    )
    db_session.add_all([admin, member])
    await db_session.flush()

    # Member's key
    raw_m_key = generate_platform_key()
    digest_m = hash_platform_key(raw_m_key, settings.key_hmac_secret)
    key_m = PlatformKey(
        org_id=org1.id,
        user_id=member.id,
        name="Member Key",
        key_prefix=raw_m_key[:16],
        key_digest=digest_m,
        credit_limit_micro=50_000_000,
        credit_remaining_micro=45_000_000,
        rpm_limit=60,
    )

    # Admin's key
    raw_a_key = generate_platform_key()
    digest_a = hash_platform_key(raw_a_key, settings.key_hmac_secret)
    key_a = PlatformKey(
        org_id=org1.id,
        user_id=admin.id,
        name="Admin Key",
        key_prefix=raw_a_key[:16],
        key_digest=digest_a,
        credit_limit_micro=100_000_000,
        credit_remaining_micro=80_000_000,
        rpm_limit=60,
    )
    db_session.add_all([key_m, key_a])
    await db_session.flush()

    # Ledger entries
    l1 = CreditLedger(
        org_id=org1.id,
        key_id=key_m.id,
        amount_micro=-5_000_000,
        balance_after_micro=45_000_000,
        reason="usage_deduction",
    )
    l2 = CreditLedger(
        org_id=org1.id,
        key_id=key_a.id,
        amount_micro=-20_000_000,
        balance_after_micro=80_000_000,
        reason="usage_deduction",
    )
    db_session.add_all([l1, l2])

    # Traces
    t1 = RequestTrace(
        org_id=org1.id,
        key_id=key_m.id,
        provider="openai",
        model="gpt-4o-mini",
        status_code=200,
        latency_ms=100,
        prompt_tokens=500,
        completion_tokens=250,
        cost_micro=225,
    )
    t2 = RequestTrace(
        org_id=org1.id,
        key_id=key_a.id,
        provider="groq",
        model="llama-3.3-70b-versatile",
        status_code=200,
        latency_ms=150,
        prompt_tokens=1000,
        completion_tokens=500,
        cost_micro=0,
    )
    db_session.add_all([t1, t2])
    await db_session.flush()

    # Generate tokens
    admin_token = create_access_token(
        {"sub": admin.id, "org_id": org1.id, "role": "admin"}, secret=settings.jwt_secret
    )
    member_token = create_access_token(
        {"sub": member.id, "org_id": org1.id, "role": "member"}, secret=settings.jwt_secret
    )

    return {
        "admin_token": admin_token,
        "member_token": member_token,
        "org_id": org1.id,
        "member_key_id": key_m.id,
        "admin_key_id": key_a.id,
    }


@pytest.mark.asyncio
async def test_admin_usage_overview(db_session: AsyncSession, usage_test_data: dict[str, str]):
    settings = Settings(env="test")
    app = create_app(settings)

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Admin gets 200 with org-wide usage
        resp = await client.get(
            "/api/admin/usage",
            headers={"Authorization": f"Bearer {usage_test_data['admin_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Both keys present
        key_ids = [k["key_id"] for k in data["by_key"]]
        assert usage_test_data["member_key_id"] in key_ids
        assert usage_test_data["admin_key_id"] in key_ids

        # Both models present
        models = [m["model"] for m in data["by_model"]]
        assert "gpt-4o-mini" in models
        assert "llama-3.3-70b-versatile" in models

        # Total credits remaining is sum of both keys (45M + 80M = 125M)
        assert data["total_credits_remaining_micro"] == 125_000_000

        # Ledger entries
        assert len(data["ledger"]) == 2

        # 2. Member gets 403 on admin usage endpoint
        resp_member = await client.get(
            "/api/admin/usage",
            headers={"Authorization": f"Bearer {usage_test_data['member_token']}"},
        )
        assert resp_member.status_code == 403


@pytest.mark.asyncio
async def test_member_usage_overview(db_session: AsyncSession, usage_test_data: dict[str, str]):
    settings = Settings(env="test")
    app = create_app(settings)

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Member only sees their own key and traces
        resp = await client.get(
            "/api/member/usage",
            headers={"Authorization": f"Bearer {usage_test_data['member_token']}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        # Only member key present
        assert len(data["by_key"]) == 1
        assert data["by_key"][0]["key_id"] == usage_test_data["member_key_id"]
        assert data["total_credits_remaining_micro"] == 45_000_000

        # Only member's ledger entry
        assert len(data["ledger"]) == 1
        assert data["ledger"][0]["key_id"] == usage_test_data["member_key_id"]
