from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_admin, require_user
from codeflux.api.schemas import (
    LimitRequestApproveRequest,
    LimitRequestCreate,
    LimitRequestResponse,
    PaginatedResponse,
)
from codeflux.api.services import LimitRequestService
from codeflux.db.models import User
from codeflux.db.session import get_db_session

# Member router
member_router = APIRouter(prefix="/api/requests", tags=["member-requests"])

# Admin router
admin_router = APIRouter(prefix="/api/admin/requests", tags=["admin-requests"])


# ============================================================================
# Member Endpoints
# ============================================================================


@member_router.post("", response_model=LimitRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_limit_request(
    payload: LimitRequestCreate,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LimitRequestResponse:
    req = await LimitRequestService.create_request(
        session=session,
        org_id=current_user.org_id,
        user_id=current_user.id,
        key_id=payload.key_id,
        requested_credit_micro=payload.requested_credit_micro,
        reason=payload.reason,
    )
    await session.commit()
    return LimitRequestResponse.model_validate(req)


@member_router.get("", response_model=PaginatedResponse[LimitRequestResponse])
async def list_member_requests(
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[LimitRequestResponse]:
    items, next_cursor = await LimitRequestService.list_member_requests(
        session=session,
        org_id=current_user.org_id,
        user_id=current_user.id,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(
        items=[LimitRequestResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


# ============================================================================
# Admin Endpoints
# ============================================================================


@admin_router.get("", response_model=PaginatedResponse[LimitRequestResponse])
async def list_admin_requests(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[LimitRequestResponse]:
    items, next_cursor = await LimitRequestService.list_admin_requests(
        session=session,
        org_id=admin.org_id,
        status_filter=status,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(
        items=[LimitRequestResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


@admin_router.post("/{id}/approve", response_model=LimitRequestResponse)
async def approve_limit_request(
    id: str,
    payload: LimitRequestApproveRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LimitRequestResponse:
    req, _ = await LimitRequestService.approve_request(
        session=session,
        org_id=admin.org_id,
        reviewer_id=admin.id,
        request_id=id,
        approved_credit_micro=payload.approved_credit_micro,
    )
    await session.commit()
    return LimitRequestResponse.model_validate(req)


@admin_router.post("/{id}/deny", response_model=LimitRequestResponse)
async def deny_limit_request(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> LimitRequestResponse:
    req = await LimitRequestService.deny_request(
        session=session,
        org_id=admin.org_id,
        reviewer_id=admin.id,
        request_id=id,
    )
    await session.commit()
    return LimitRequestResponse.model_validate(req)
