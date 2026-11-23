from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_user
from codeflux.api.schemas import PaginatedResponse, SessionDetailResponse, SessionItem
from codeflux.db.models import User
from codeflux.db.session import get_db_session
from codeflux.sessions.service import (
    delete_member_session,
    get_member_session_detail,
    list_member_sessions,
)

router = APIRouter(prefix="/api/member/sessions", tags=["sessions"])


@router.get("", response_model=PaginatedResponse[SessionItem])
async def list_sessions(
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[SessionItem]:
    """List sessions owned by member's keys (or all org sessions for admin) with cursor pagination."""
    is_admin = current_user.role == "admin"
    items, next_cursor = await list_member_sessions(
        session,
        org_id=current_user.org_id,
        user_id=current_user.id,
        is_admin=is_admin,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(items=items, next_cursor=next_cursor)


@router.get("/{session_id}", response_model=SessionDetailResponse)
async def get_session(
    session_id: str,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SessionDetailResponse:
    """Retrieve full session detail with messages, subject to 24h expiration on read."""
    is_admin = current_user.role == "admin"
    try:
        detail = await get_member_session_detail(
            session,
            session_id=session_id,
            org_id=current_user.org_id,
            user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied", "message": str(exc)},
        ) from exc

    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Session not found or expired"},
        )
    return detail


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user: Annotated[User, Depends(require_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, Any]:
    """Delete a session and cascade delete its messages."""
    is_admin = current_user.role == "admin"
    try:
        deleted = await delete_member_session(
            session,
            session_id=session_id,
            org_id=current_user.org_id,
            user_id=current_user.id,
            is_admin=is_admin,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "permission_denied", "message": str(exc)},
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "session_not_found", "message": "Session not found"},
        )
    return {"deleted": True, "id": session_id}
