from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
from codeflux.db.models import CreditLedger, PlatformKey
from codeflux.db.session import get_db_session
from codeflux.settings import Settings


@pytest.fixture
def app_with_session(db_session: AsyncSession) -> FastAPI:
    settings = Settings(env="test")
    app = create_app(settings)

    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session
    return app


@pytest.mark.asyncio
async def test_limit_requests_flow_and_approval(
    app_with_session: FastAPI, db_session: AsyncSession
):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Admin signup
        admin_signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Req Org", "email": "admin@req.com", "password": "Password123!"},
        )
        admin_token = admin_signup.json()["token"]
        org_id = admin_signup.json()["user"]["org_id"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 2. Member signup with invite code
        member_signup = await client.post(
            "/api/auth/signup",
            json={"invite_code": org_id, "email": "member@req.com", "password": "Password123!"},
        )
        member_token = member_signup.json()["token"]
        member_id = member_signup.json()["user"]["id"]
        member_headers = {"Authorization": f"Bearer {member_token}"}

        # 3. Admin creates key for member with $10 limit
        key_resp = await client.post(
            "/api/admin/keys",
            headers=admin_headers,
            json={
                "user_id": member_id,
                "name": "Member Key",
                "credit_limit_micro": 10_000_000,
            },
        )
        key_id = key_resp.json()["id"]

        # 4. Member creates a limit request for $25
        req_resp = await client.post(
            "/api/requests",
            headers=member_headers,
            json={
                "key_id": key_id,
                "requested_credit_micro": 25_000_000,
                "reason": "Need more compute for batch eval",
            },
        )
        assert req_resp.status_code == 201
        req_data = req_resp.json()
        assert req_data["status"] == "pending"
        assert req_data["requested_credit_micro"] == 25_000_000
        req_id = req_data["id"]

        # 5. Member lists their own requests
        member_list = await client.get("/api/requests", headers=member_headers)
        assert member_list.status_code == 200
        assert len(member_list.json()["items"]) == 1
        assert member_list.json()["items"][0]["id"] == req_id

        # 6. Admin lists pending requests
        admin_list = await client.get("/api/admin/requests?status=pending", headers=admin_headers)
        assert admin_list.status_code == 200
        assert len(admin_list.json()["items"]) == 1

        # 7. Admin approves with edited limit ($30 instead of $25)
        approve_resp = await client.post(
            f"/api/admin/requests/{req_id}/approve",
            headers=admin_headers,
            json={"approved_credit_micro": 30_000_000},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["status"] == "approved"

        # Verify key limits were updated
        key_db = await db_session.execute(select(PlatformKey).where(PlatformKey.id == key_id))
        key = key_db.scalar_one()
        assert key.credit_limit_micro == 30_000_000
        # Delta was 30_000_000 - 10_000_000 = 20_000_000 added to credit_remaining_micro
        assert key.credit_remaining_micro == 30_000_000

        # Verify ledger row was written
        ledger_res = await db_session.execute(
            select(CreditLedger).where(CreditLedger.key_id == key_id)
        )
        ledgers = list(ledger_res.scalars().all())
        # Initial grant + approval
        assert len(ledgers) == 2
        approval_ledger = ledgers[1]
        assert approval_ledger.amount_micro == 20_000_000
        assert approval_ledger.balance_after_micro == 30_000_000
        assert approval_ledger.reason == f"limit_request_approved:{req_id}"

        # 8. Create another request and deny it
        req2_resp = await client.post(
            "/api/requests",
            headers=member_headers,
            json={"key_id": key_id, "requested_credit_micro": 50_000_000},
        )
        req2_id = req2_resp.json()["id"]

        deny_resp = await client.post(
            f"/api/admin/requests/{req2_id}/deny",
            headers=admin_headers,
        )
        assert deny_resp.status_code == 200
        assert deny_resp.json()["status"] == "denied"
