from __future__ import annotations

import httpx
import pytest
import respx
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
async def test_gate_check_member_gets_403_on_admin_routes(app_with_session: FastAPI):
    """Gate Check 1: API tests show a member gets 403 on admin routes."""
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup admin and org
        admin_signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Gate Org", "email": "admin@gate.com", "password": "Password123!"},
        )
        org_id = admin_signup.json()["user"]["org_id"]

        # Signup member
        member_signup = await client.post(
            "/api/auth/signup",
            json={"invite_code": org_id, "email": "member@gate.com", "password": "Password123!"},
        )
        member_token = member_signup.json()["token"]
        member_headers = {"Authorization": f"Bearer {member_token}"}

        # Check all admin routes return 403 Forbidden
        routes_to_test = [
            ("GET", "/api/admin/vault"),
            ("POST", "/api/admin/vault"),
            ("GET", "/api/admin/keys"),
            ("POST", "/api/admin/keys"),
            ("GET", "/api/admin/routes"),
            ("POST", "/api/admin/routes"),
            ("GET", "/api/admin/requests"),
        ]

        for method, path in routes_to_test:
            if method == "GET":
                resp = await client.get(path, headers=member_headers)
            else:
                resp = await client.post(path, headers=member_headers, json={})
            assert resp.status_code == 403, f"{method} {path} did not return 403"
            data = resp.json()
            assert "error" in data
            assert data["error"]["code"] == "forbidden"


@pytest.mark.asyncio
async def test_gate_check_cross_org_read_returns_404(app_with_session: FastAPI):
    """Gate Check 2: A cross-org read returns 404."""
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Org A
        signup_a = await client.post(
            "/api/auth/signup",
            json={"org_name": "Org A", "email": "admin@orga.com", "password": "Password123!"},
        )
        token_a = signup_a.json()["token"]
        user_a_id = signup_a.json()["user"]["id"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # Org B
        signup_b = await client.post(
            "/api/auth/signup",
            json={"org_name": "Org B", "email": "admin@orgb.com", "password": "Password123!"},
        )
        token_b = signup_b.json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # Create key in Org A
        key_resp = await client.post(
            "/api/admin/keys",
            headers=headers_a,
            json={"user_id": user_a_id, "name": "Key A", "credit_limit_micro": 1000},
        )
        key_a_id = key_resp.json()["id"]

        # Create route in Org A
        route_resp = await client.post(
            "/api/admin/routes",
            headers=headers_a,
            json={
                "alias": "route-a",
                "strategy": "priority",
                "candidates": [{"provider": "openai", "model": "gpt-4o"}],
            },
        )
        route_a_id = route_resp.json()["id"]

        # Org B admin tries to read Org A's key -> 404
        cross_key_resp = await client.get(f"/api/admin/keys/{key_a_id}", headers=headers_b)
        assert cross_key_resp.status_code == 404
        assert cross_key_resp.json()["error"]["code"] == "not_found"

        # Org B admin tries to read Org A's route -> 404
        cross_route_resp = await client.get(f"/api/admin/routes/{route_a_id}", headers=headers_b)
        assert cross_route_resp.status_code == 404
        assert cross_route_resp.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_gate_check_plaintext_key_only_on_create_and_no_secrets_leaked(
    app_with_session: FastAPI,
):
    """Gate Checks 3 & 4:

    - The platform key plaintext appears only in the create response.
    - No response contains an encrypted key or a digest.
    """
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Gate Org 2", "email": "admin@gate2.com", "password": "Password123!"},
        )
        token = signup.json()["token"]
        user_id = signup.json()["user"]["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Platform Key
        create_resp = await client.post(
            "/api/admin/keys",
            headers=headers,
            json={"user_id": user_id, "name": "Secret Test Key", "credit_limit_micro": 5000},
        )
        assert create_resp.status_code == 201
        create_data = create_resp.json()

        # Plaintext appears in create response
        assert "key" in create_data
        plaintext = create_data["key"]
        assert plaintext.startswith("ok_live_")
        key_id = create_data["id"]

        # But digest must NOT appear
        assert "key_digest" not in create_data
        assert "digest" not in create_data

        # 2. List platform keys: plaintext key and digest must NOT appear
        list_resp = await client.get("/api/admin/keys", headers=headers)
        assert list_resp.status_code == 200
        list_text = list_resp.text
        assert plaintext not in list_text
        assert "key_digest" not in list_text
        assert "encrypted_key" not in list_text

        # 3. Get platform key: plaintext key and digest must NOT appear
        get_resp = await client.get(f"/api/admin/keys/{key_id}", headers=headers)
        assert get_resp.status_code == 200
        get_text = get_resp.text
        assert plaintext not in get_text
        assert "key_digest" not in get_text
        assert "encrypted_key" not in get_text

        # 4. Vault: add provider key and ensure encrypted key is NOT returned
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.get("https://api.openai.com/v1/models").respond(200, json={"data": []})

            vault_resp = await client.post(
                "/api/admin/vault",
                headers=headers,
                json={"provider": "openai", "api_key": "sk-real-super-secret-1234"},
            )
            assert vault_resp.status_code == 201
            vault_data = vault_resp.json()
            assert "encrypted_key" not in vault_data
            assert "sk-real-super-secret-1234" not in vault_resp.text
            assert vault_data["key_hint"] == "1234"

            # List vault: encrypted_key must not be in list response
            vault_list_resp = await client.get("/api/admin/vault", headers=headers)
            assert "encrypted_key" not in vault_list_resp.text
            assert "sk-real-super-secret-1234" not in vault_list_resp.text


@pytest.mark.asyncio
async def test_gate_check_approving_request_changes_limit_and_writes_ledger_row(
    app_with_session: FastAPI, db_session: AsyncSession
):
    """Gate Check 5: Approving a request changes the limit and writes a ledger row."""
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Gate Org 3", "email": "admin@gate3.com", "password": "Password123!"},
        )
        token = signup.json()["token"]
        user_id = signup.json()["user"]["id"]
        headers = {"Authorization": f"Bearer {token}"}

        # Create key with $5 (5_000_000 micro-USD)
        key_resp = await client.post(
            "/api/admin/keys",
            headers=headers,
            json={"user_id": user_id, "name": "Gate Key", "credit_limit_micro": 5_000_000},
        )
        key_id = key_resp.json()["id"]

        # Create request for $15 (15_000_000 micro-USD)
        req_resp = await client.post(
            "/api/requests",
            headers=headers,
            json={"key_id": key_id, "requested_credit_micro": 15_000_000},
        )
        req_id = req_resp.json()["id"]

        # Approve request with $20 (20_000_000 micro-USD)
        approve_resp = await client.post(
            f"/api/admin/requests/{req_id}/approve",
            headers=headers,
            json={"approved_credit_micro": 20_000_000},
        )
        assert approve_resp.status_code == 200

        # Verify limit changed
        key_res = await db_session.execute(select(PlatformKey).where(PlatformKey.id == key_id))
        key = key_res.scalar_one()
        assert key.credit_limit_micro == 20_000_000
        assert key.credit_remaining_micro == 20_000_000

        # Verify ledger row was written
        ledger_res = await db_session.execute(
            select(CreditLedger).where(
                CreditLedger.key_id == key_id,
                CreditLedger.reason == f"limit_request_approved:{req_id}",
            )
        )
        ledger_entry = ledger_res.scalar_one_or_none()
        assert ledger_entry is not None
        assert ledger_entry.amount_micro == 15_000_000  # 20M - 5M delta
        assert ledger_entry.balance_after_micro == 20_000_000
