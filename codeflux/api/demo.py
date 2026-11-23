from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from codeflux.api.deps import require_admin
from codeflux.db.models import User
from codeflux.settings import Settings

demo_router = APIRouter(prefix="/api/admin/demo", tags=["demo"])


class OutageToggleRequest(BaseModel):
    provider: str
    outage: bool | None = None


class OutageToggleResponse(BaseModel):
    provider: str
    outage: bool


@demo_router.post("/outage", response_model=OutageToggleResponse)
async def toggle_demo_outage(
    payload: OutageToggleRequest,
    current_user: Annotated[User, Depends(require_admin)],
    request: Request,
) -> dict[str, Any]:
    """Toggle in-memory simulated outage for a provider when DEMO_MODE is on."""
    settings = getattr(request.app.state, "settings", None) or Settings()
    if not settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "demo_mode_disabled", "message": "DEMO_MODE is not enabled"},
        )

    p = payload.provider.lower()
    demo_outages: set[str] = getattr(request.app.state, "demo_outages", None)
    if demo_outages is None:
        demo_outages = set()
        request.app.state.demo_outages = demo_outages

    if payload.outage is None:
        if p in demo_outages:
            demo_outages.discard(p)
            active = False
        else:
            demo_outages.add(p)
            active = True
    elif payload.outage:
        demo_outages.add(p)
        active = True
    else:
        demo_outages.discard(p)
        active = False

    return {"provider": payload.provider, "outage": active}
