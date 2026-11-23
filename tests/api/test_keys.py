from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
from codeflux.db.models import CreditLedger
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
async def test_platform_keys_crud_and_ledger(app_with_session: FastAPI, db_session: AsyncSession):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup admin
        signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Keys Org", "email": "admin@keys.com", "password": "Password123!"},
        )
        token = signup.json()["token"]
        user_id = signup.json()["user"]["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create platform key
        create_resp = await client.post(
            "/api/admin/keys",
            headers=headers,
            json={
                "user_id": user_id,
                "name": "Dev Team Key",
                "credit_limit_micro": 50_000_000,  # $50
                "rpm_limit": 100,
                "allowed_routes": ["default", "fast"],
            },
        )
        assert create_resp.status_code == 201
        created_data = create_resp.json()
        assert created_data["name"] == "Dev Team Key"
        assert created_data["credit_limit_micro"] == 50_000_000
        assert created_data["credit_remaining_micro"] == 50_000_000
        assert "key" in created_data
        assert created_data["key"].startswith("ok_live_")
        assert "key_digest" not in created_data
        key_id = created_data["id"]

        # Verify initial credit ledger row created
        ledger_res = await db_session.execute(
            select(CreditLedger).where(CreditLedger.key_id == key_id)
        )
        ledger_rows = list(ledger_res.scalars().all())
        assert len(ledger_rows) == 1
        assert ledger_rows[0].amount_micro == 50_000_000
        assert ledger_rows[0].reason == "initial_grant"

        # 2. List platform keys (plaintext key must NOT appear)
        list_resp = await client.get("/api/admin/keys", headers=headers)
        assert list_resp.status_code == 200
        list_items = list_resp.json()["items"]
        assert len(list_items) == 1
        assert list_items[0]["id"] == key_id
        assert "key" not in list_items[0]
        assert "key_digest" not in list_items[0]

        # 3. Get platform key by ID (plaintext key must NOT appear)
        get_resp = await client.get(f"/api/admin/keys/{key_id}", headers=headers)
        assert get_resp.status_code == 200
        assert "key" not in get_resp.json()
        assert "key_digest" not in get_resp.json()

        # 4. Patch key limits (increase limit by $20 -> 70_000_000)
        patch_resp = await client.patch(
            f"/api/admin/keys/{key_id}",
            headers=headers,
            json={"credit_limit_micro": 70_000_000, "rpm_limit": 120},
        )
        assert patch_resp.status_code == 200
        patched_data = patch_resp.json()
        assert patched_data["credit_limit_micro"] == 70_000_000
        assert patched_data["credit_remaining_micro"] == 70_000_000
        assert patched_data["rpm_limit"] == 120

        # Verify ledger row for the delta
        ledger_res2 = await db_session.execute(
            select(CreditLedger).where(CreditLedger.key_id == key_id)
        )
        all_ledger = list(ledger_res2.scalars().all())
        assert len(all_ledger) == 2
        assert all_ledger[1].amount_micro == 20_000_000
        assert all_ledger[1].reason == "admin_adjustment"

        # 5. Revoke platform key
        revoke_resp = await client.delete(f"/api/admin/keys/{key_id}", headers=headers)
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked_at"] is not None
