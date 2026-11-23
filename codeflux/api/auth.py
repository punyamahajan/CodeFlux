from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_user
from codeflux.api.schemas import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    SignupRequest,
    UserResponse,
)
from codeflux.api.services import AuthService
from codeflux.db.models import Organization, User
from codeflux.db.session import get_db_session
from codeflux.security.tokens import COOKIE_MAX_AGE, COOKIE_NAME
from codeflux.settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=COOKIE_MAX_AGE,
        samesite="lax",
        secure=False,  # Set to True in HTTPS production if needed
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthResponse:
    settings = Settings()
    if payload.org_name:
        user, _, token = await AuthService.admin_signup(
            session=session,
            org_name=payload.org_name,
            email=payload.email,
            password=payload.password,
            jwt_secret=settings.jwt_secret,
        )
    elif payload.invite_code:
        user, _, token = await AuthService.member_signup(
            session=session,
            invite_code=payload.invite_code,
            email=payload.email,
            password=payload.password,
            jwt_secret=settings.jwt_secret,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "missing_signup_field",
                "message": "Either 'org_name' (for admin) or 'invite_code' (for member) must be provided",
            },
        )

    await session.commit()
    _set_auth_cookie(response, token)
    return AuthResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> AuthResponse:
    settings = Settings()
    user, _, token = await AuthService.login(
        session=session,
        email=payload.email,
        password=payload.password,
        jwt_secret=settings.jwt_secret,
        org_id=payload.org_id,
    )
    _set_auth_cookie(response, token)
    return AuthResponse(token=token, user=UserResponse.model_validate(user))


@router.post("/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(key=COOKIE_NAME)
    return {"message": "logged out"}


@router.get("/me", response_model=MeResponse)
async def me(
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MeResponse:
    from sqlalchemy import select

    org_res = await session.execute(
        select(Organization).where(Organization.id == current_user.org_id)
    )
    org = org_res.scalar_one()
    return MeResponse(
        id=current_user.id,
        org_id=current_user.org_id,
        email=current_user.email,
        role=current_user.role,
        org_name=org.name,
        created_at=current_user.created_at,
    )
