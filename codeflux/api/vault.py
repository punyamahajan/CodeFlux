from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_admin
from codeflux.api.schemas import (
    PaginatedResponse,
    VaultAddRequest,
    VaultCredentialResponse,
    VaultPatchRequest,
)
from codeflux.api.services import VaultService
from codeflux.db.models import User
from codeflux.db.session import get_db_session
from codeflux.settings import Settings

router = APIRouter(prefix="/api/admin/vault", tags=["admin-vault"])


@router.post("", response_model=VaultCredentialResponse, status_code=status.HTTP_201_CREATED)
async def add_vault_credential(
    payload: VaultAddRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VaultCredentialResponse:
    settings = Settings()
    # Use existing app client if available, else temporary client
    client = getattr(request.app.state, "client", None)
    if client is None:
        async with httpx.AsyncClient() as temp_client:
            cred = await VaultService.add_credential(
                session=session,
                client=temp_client,
                org_id=admin.org_id,
                provider=payload.provider,
                api_key=payload.api_key,
                master_key=settings.master_key,
            )
    else:
        cred = await VaultService.add_credential(
            session=session,
            client=client,
            org_id=admin.org_id,
            provider=payload.provider,
            api_key=payload.api_key,
            master_key=settings.master_key,
        )

    await session.commit()
    return VaultCredentialResponse.model_validate(cred)


@router.get("", response_model=PaginatedResponse[VaultCredentialResponse])
async def list_vault_credentials(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[VaultCredentialResponse]:
    items, next_cursor = await VaultService.list_credentials(
        session=session,
        org_id=admin.org_id,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(
        items=[VaultCredentialResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


@router.patch("/{id}", response_model=VaultCredentialResponse)
async def toggle_vault_credential(
    id: str,
    payload: VaultPatchRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> VaultCredentialResponse:
    cred = await VaultService.toggle_credential(
        session=session,
        org_id=admin.org_id,
        cred_id=id,
        enabled=payload.enabled,
    )
    await session.commit()
    return VaultCredentialResponse.model_validate(cred)


@router.delete("/{id}")
async def delete_vault_credential(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    await VaultService.delete_credential(
        session=session,
        org_id=admin.org_id,
        cred_id=id,
    )
    await session.commit()
    return {"message": "deleted"}
