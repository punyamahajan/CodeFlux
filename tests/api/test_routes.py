from __future__ import annotations

import httpx
import pytest
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
async def test_routes_crud(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Signup admin
        signup = await client.post(
            "/api/auth/signup",
            json={
                "org_name": "Routes Org",
                "email": "admin@routes.com",
                "password": "Password123!",
            },
        )
        token = signup.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create Route
        create_resp = await client.post(
            "/api/admin/routes",
            headers=headers,
            json={
                "alias": "smart-fallback",
                "strategy": "priority",
                "task_tag": "reasoning",
                "candidates": [
                    {"provider": "openai", "model": "gpt-4o", "weight": 1.0},
                    {"provider": "gemini", "model": "gemini-2.0-flash", "weight": 1.0},
                ],
            },
        )
        assert create_resp.status_code == 201
        route = create_resp.json()
        assert route["alias"] == "smart-fallback"
        assert len(route["candidates"]) == 2
        route_id = route["id"]

        # Duplicate alias in same org -> 409
        dup_resp = await client.post(
            "/api/admin/routes",
            headers=headers,
            json={
                "alias": "smart-fallback",
                "strategy": "priority",
                "candidates": [{"provider": "openai", "model": "gpt-4o"}],
            },
        )
        assert dup_resp.status_code == 409
        assert dup_resp.json()["error"]["code"] == "alias_conflict"

        # 2. List Routes
        list_resp = await client.get("/api/admin/routes", headers=headers)
        assert list_resp.status_code == 200
        assert len(list_resp.json()["items"]) == 1

        # 3. Get Route
        get_resp = await client.get(f"/api/admin/routes/{route_id}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == route_id

        # 4. Update Route
        patch_resp = await client.patch(
            f"/api/admin/routes/{route_id}",
            headers=headers,
            json={"strategy": "least-latency"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["strategy"] == "least-latency"

        # 5. Delete Route
        del_resp = await client.delete(f"/api/admin/routes/{route_id}", headers=headers)
        assert del_resp.status_code == 200

        # Verify not found
        get_after = await client.get(f"/api/admin/routes/{route_id}", headers=headers)
        assert get_after.status_code == 404
