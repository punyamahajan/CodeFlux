from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_admin
from codeflux.api.schemas import (
    PaginatedResponse,
    RouteCreateRequest,
    RouteResponse,
    RouteUpdateRequest,
)
from codeflux.api.services import RouteService
from codeflux.db.models import User
from codeflux.db.session import get_db_session

router = APIRouter(prefix="/api/admin/routes", tags=["admin-routes"])


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_route(
    payload: RouteCreateRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RouteResponse:
    candidates_dict = [c.model_dump() for c in payload.candidates]
    route = await RouteService.create_route(
        session=session,
        org_id=admin.org_id,
        alias=payload.alias,
        strategy=payload.strategy,
        task_tag=payload.task_tag,
        candidates=candidates_dict,
    )
    await session.commit()
    return RouteResponse.model_validate(route)


@router.get("", response_model=PaginatedResponse[RouteResponse])
async def list_routes(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> PaginatedResponse[RouteResponse]:
    items, next_cursor = await RouteService.list_routes(
        session=session,
        org_id=admin.org_id,
        limit=limit,
        cursor=cursor,
    )
    return PaginatedResponse(
        items=[RouteResponse.model_validate(i) for i in items],
        next_cursor=next_cursor,
    )


@router.get("/{id}", response_model=RouteResponse)
async def get_route(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RouteResponse:
    route = await RouteService.get_route(session, admin.org_id, id)
    return RouteResponse.model_validate(route)


@router.patch("/{id}", response_model=RouteResponse)
async def update_route(
    id: str,
    payload: RouteUpdateRequest,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RouteResponse:
    candidates_dict = (
        [c.model_dump() for c in payload.candidates] if payload.candidates is not None else None
    )
    route = await RouteService.update_route(
        session=session,
        org_id=admin.org_id,
        route_id=id,
        alias=payload.alias,
        strategy=payload.strategy,
        task_tag=payload.task_tag,
        candidates=candidates_dict,
    )
    await session.commit()
    return RouteResponse.model_validate(route)


@router.delete("/{id}")
async def delete_route(
    id: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, str]:
    await RouteService.delete_route(session, admin.org_id, id)
    await session.commit()
    return {"message": "deleted"}
