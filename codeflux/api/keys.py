from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_admin
from codeflux.api.schemas import (
    PaginatedResponse,
    PlatformKeyCreatedResponse,
    PlatformKeyCreateRequest,
    PlatformKeyPatchRequest,
    PlatformKeyResponse,
)
from codeflux.api.services import PlatformKeyService
from codeflux.db.models import User
from codeflux.db.session import get_db_session
from codeflux.settings import Settings

router = APIRouter(prefix="/api/admin/keys", tags=["admin-keys"])


@router.post("", response_model=PlatformKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_platform_key(
    payload: PlatformKeyCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformKeyCreatedResponse:
    settings = Settings()
    key, plaintext = await PlatformKeyService.create_key(
        session=session,
        org_id=admin.org_id,
        user_id=payload.user_id,
        name=payload.name,
        credit_limit_micro=payload.credit_limit_micro,
        rpm_limit=payload.rpm_limit,
        allowed_routes=payload.allowed_routes,
        expires_at=payload.expires_at,
        hmac_secret=settings.key_hmac_secret,
    )
    await session.commit()

    key_dict = {
        "id": key.id,
        "user_id": key.user_id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "credit_limit_micro": key.credit_limit_micro,
        "credit_remaining_micro": key.credit_remaining_micro,
        "rpm_limit": key.rpm_limit,
        "allowed_routes": key.allowed_routes,
        "expires_at": key.expires_at,
        "revoked_at": key.revoked_at,
        "created_at": key.created_at,
        "last_used_at": key.last_used_at,
        "key": plaintext,  # Returned only once!
    }
    return PlatformKeyCreatedResponse.model_validate(key_dict)


@router.get("", response_model=PaginatedResponse[PlatformKeyResponse])
async def list_platform_keys(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[PlatformKeyResponse]:
    items, next_cursor = await PlatformKeyService.list_keys(
        session=session,
        org_id=admin.org_id,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(
        items=[PlatformKeyResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


@router.get("/{id}", response_model=PlatformKeyResponse)
async def get_platform_key(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformKeyResponse:
    key = await PlatformKeyService.get_key(session, admin.org_id, id)
    return PlatformKeyResponse.model_validate(key)


@router.patch("/{id}", response_model=PlatformKeyResponse)
async def patch_platform_key(
    id: str,
    payload: PlatformKeyPatchRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformKeyResponse:
    key = await PlatformKeyService.patch_key(
        session=session,
        org_id=admin.org_id,
        key_id=id,
        name=payload.name,
        credit_limit_micro=payload.credit_limit_micro,
        rpm_limit=payload.rpm_limit,
        allowed_routes=payload.allowed_routes,
        expires_at=payload.expires_at,
    )
    await session.commit()
    return PlatformKeyResponse.model_validate(key)


@router.delete("/{id}", response_model=PlatformKeyResponse)
async def revoke_platform_key(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformKeyResponse:
    key = await PlatformKeyService.revoke_key(session, admin.org_id, id)
    await session.commit()
    return PlatformKeyResponse.model_validate(key)
