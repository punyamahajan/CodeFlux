from __future__ import annotations

import httpx
import pytest
import respx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
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
async def test_vault_crud_and_validation(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup admin
        signup = await client.post(
            "/api/auth/signup",
            json={"org_name": "Vault Org", "email": "admin@vault.com", "password": "Password123!"},
        )
        token = signup.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Add key with successful mock provider probe
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.get("https://api.openai.com/v1/models").respond(200, json={"data": []})

            resp = await client.post(
                "/api/admin/vault",
                headers=headers,
                json={"provider": "openai", "api_key": "sk-proj-test-key-1234"},
            )
            assert resp.status_code == 201
            cred = resp.json()
            assert cred["provider"] == "openai"
            assert cred["key_hint"] == "1234"
            assert cred["enabled"] is True
            # Never return encrypted_key or raw key
            assert "encrypted_key" not in cred
            assert "api_key" not in cred
            cred_id = cred["id"]

        # 2. Add key with failed mock provider probe -> 400
        with respx.mock(assert_all_called=False) as respx_mock:
            respx_mock.get("https://api.openai.com/v1/models").respond(
                401, json={"error": "invalid key"}
            )

            fail_resp = await client.post(
                "/api/admin/vault",
                headers=headers,
                json={"provider": "openai", "api_key": "sk-bad-key"},
            )
            assert fail_resp.status_code == 400
            assert fail_resp.json()["error"]["code"] == "invalid_provider_key"

        # 3. List credentials
        list_resp = await client.get("/api/admin/vault", headers=headers)
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == cred_id

        # 4. Toggle credential
        patch_resp = await client.patch(
            f"/api/admin/vault/{cred_id}",
            headers=headers,
            json={"enabled": False},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["enabled"] is False

        # 5. Delete credential
        del_resp = await client.delete(f"/api/admin/vault/{cred_id}", headers=headers)
        assert del_resp.status_code == 200

        # Verify list is empty
        list_after = await client.get("/api/admin/vault", headers=headers)
        assert len(list_after.json()["items"]) == 0
