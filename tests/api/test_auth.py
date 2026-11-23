from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.app import create_app
from codeflux.db.session import get_db_session
from codeflux.security.tokens import COOKIE_NAME
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
async def test_admin_signup_creates_org_and_admin(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/signup",
            json={
                "org_name": "Acme Corp",
                "email": "admin@acme.com",
                "password": "Password123!",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"
        assert data["user"]["email"] == "admin@acme.com"
        assert data["user"]["org_id"].startswith("org_")
        assert COOKIE_NAME in resp.cookies


@pytest.mark.asyncio
async def test_member_signup_with_invite_code(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Admin signs up
        admin_resp = await client.post(
            "/api/auth/signup",
            json={
                "org_name": "Initech",
                "email": "boss@initech.com",
                "password": "Password123!",
            },
        )
        assert admin_resp.status_code == 201
        org_id = admin_resp.json()["user"]["org_id"]

        # 2. Member joins with invite code (org_id)
        member_resp = await client.post(
            "/api/auth/signup",
            json={
                "invite_code": org_id,
                "email": "peter@initech.com",
                "password": "Password123!",
            },
        )
        assert member_resp.status_code == 201
        member_data = member_resp.json()
        assert member_data["user"]["role"] == "member"
        assert member_data["user"]["org_id"] == org_id


@pytest.mark.asyncio
async def test_signup_with_invalid_invite_code_returns_404(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/signup",
            json={
                "invite_code": "org_nonexistent",
                "email": "test@nowhere.com",
                "password": "Password123!",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "invalid_invite"


@pytest.mark.asyncio
async def test_login_and_me(app_with_session: FastAPI):
    transport = httpx.ASGITransport(app=app_with_session)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Create user
        await client.post(
            "/api/auth/signup",
            json={
                "org_name": "Wayne Enterprises",
                "email": "bruce@wayne.com",
                "password": "BatPassword123!",
            },
        )

        # Login with correct password
        login_resp = await client.post(
            "/api/auth/login",
            json={"email": "bruce@wayne.com", "password": "BatPassword123!"},
        )
        assert login_resp.status_code == 200
        token = login_resp.json()["token"]

        # /me with cookie
        client.cookies.set(COOKIE_NAME, token)
        me_resp = await client.get("/api/auth/me")
        assert me_resp.status_code == 200
        me_data = me_resp.json()
        assert me_data["email"] == "bruce@wayne.com"
        assert me_data["org_name"] == "Wayne Enterprises"

        # Logout
        logout_resp = await client.post("/api/auth/logout")
        assert logout_resp.status_code == 200

        # Login with wrong password returns 401
        wrong_resp = await client.post(
            "/api/auth/login",
            json={"email": "bruce@wayne.com", "password": "WrongPassword!"},
        )
        assert wrong_resp.status_code == 401
        assert wrong_resp.json()["error"]["code"] == "invalid_credentials"
