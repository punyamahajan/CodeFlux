from __future__ import annotations

from datetime import timedelta
from typing import Annotated

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_admin, require_user
from codeflux.app import create_app
from codeflux.db.models import Org, User
from codeflux.db.session import get_db_session
from codeflux.security.passwords import hash_password
from codeflux.security.tokens import COOKIE_NAME, create_access_token
from codeflux.settings import Settings


@pytest.fixture
def test_app(db_session: AsyncSession) -> FastAPI:
    settings = Settings(env="test")
    app = create_app(settings)

    # Override get_db_session to use test transaction session
    async def override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db_session

    # Dummy test routes under /api
    @app.get("/api/test/user")
    async def get_test_user(user: Annotated[User, Depends(require_user)]):
        return {"id": user.id, "email": user.email, "role": user.role}

    @app.get("/api/test/admin")
    async def get_test_admin(user: Annotated[User, Depends(require_admin)]):
        return {"id": user.id, "email": user.email, "role": user.role}

    return app


@pytest.mark.asyncio
async def test_require_user_without_token_returns_401(test_app: FastAPI):
    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/test/user")
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "unauthorized"


@pytest.mark.asyncio
async def test_require_user_with_expired_token_returns_401(
    test_app: FastAPI, db_session: AsyncSession
):
    settings = Settings(env="test")
    # Insert org and user
    org = Org(id="org_depstest1", name="Deps Org")
    db_session.add(org)
    user = User(
        id="usr_depstest1",
        org_id=org.id,
        email="test@example.com",
        password_hash=hash_password("pw123"),
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(
        {"sub": user.id, "org_id": org.id, "role": user.role},
        settings.jwt_secret,
        expires_delta=timedelta(seconds=-10),
    )

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/test/user",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data
        assert data["error"]["code"] == "token_expired"


@pytest.mark.asyncio
async def test_require_user_with_valid_bearer_and_cookie(
    test_app: FastAPI, db_session: AsyncSession
):
    settings = Settings(env="test")
    org = Org(id="org_depstest2", name="Deps Org 2")
    db_session.add(org)
    user = User(
        id="usr_depstest2",
        org_id=org.id,
        email="bearer@example.com",
        password_hash=hash_password("pw123"),
        role="member",
    )
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(
        {"sub": user.id, "org_id": org.id, "role": user.role},
        settings.jwt_secret,
    )

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Test via Bearer header
        resp_bearer = await client.get(
            "/api/test/user",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp_bearer.status_code == 200
        assert resp_bearer.json()["id"] == user.id

        # 2. Test via httpOnly cookie
        client.cookies.set(COOKIE_NAME, token)
        resp_cookie = await client.get("/api/test/user")
        assert resp_cookie.status_code == 200
        assert resp_cookie.json()["id"] == user.id


@pytest.mark.asyncio
async def test_require_admin_allows_admin_rejects_member(
    test_app: FastAPI, db_session: AsyncSession
):
    settings = Settings(env="test")
    org = Org(id="org_depstest3", name="Deps Org 3")
    db_session.add(org)

    member_user = User(
        id="usr_member3",
        org_id=org.id,
        email="member@example.com",
        password_hash=hash_password("pw123"),
        role="member",
    )
    admin_user = User(
        id="usr_admin3",
        org_id=org.id,
        email="admin@example.com",
        password_hash=hash_password("pw123"),
        role="admin",
    )
    db_session.add_all([member_user, admin_user])
    await db_session.flush()

    member_token = create_access_token(
        {"sub": member_user.id, "org_id": org.id, "role": member_user.role},
        settings.jwt_secret,
    )
    admin_token = create_access_token(
        {"sub": admin_user.id, "org_id": org.id, "role": admin_user.role},
        settings.jwt_secret,
    )

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Member should get 403 Forbidden with standard /api error envelope
        resp_member = await client.get(
            "/api/test/admin",
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert resp_member.status_code == 403
        data_member = resp_member.json()
        assert "error" in data_member
        assert data_member["error"]["code"] == "forbidden"

        # Admin should succeed with 200
        resp_admin = await client.get(
            "/api/test/admin",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp_admin.status_code == 200
        assert resp_admin.json()["id"] == admin_user.id
