from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import get_current_user, require_admin
from codeflux.api.schemas import UsageOverviewResponse
from codeflux.api.services import UsageService
from codeflux.db.models import User
from codeflux.db.session import get_db_session

admin_usage_router = APIRouter(prefix="/api/admin/usage", tags=["admin-usage"])
member_usage_router = APIRouter(prefix="/api/member/usage", tags=["member-usage"])


@admin_usage_router.get("", response_model=UsageOverviewResponse)
async def get_admin_usage(
    current_user: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, object]:
    """Admin usage overview: aggregates by key and model across the organization, plus ledger entries."""
    return await UsageService.get_usage_overview(
        session=session,
        org_id=current_user.org_id,
        user_id=None,
        limit=limit,
        cursor=cursor,
    )


@member_usage_router.get("", response_model=UsageOverviewResponse)
async def get_member_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, object]:
    """Member usage overview: aggregates by key and model for member's own keys, plus ledger entries."""
    return await UsageService.get_usage_overview(
        session=session,
        org_id=current_user.org_id,
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )
