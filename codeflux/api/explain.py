"""Explain API router.

GET  /api/explain/{kind}/{id}
POST /api/explain/{kind}/{id}/narrate

``kind`` must be one of: trace, cost, credits, usage, blocked, compare, debate.

Trace-based kinds look up RequestTrace; arena kinds (compare, debate) look up ArenaRun.
Members may only read records belonging to their own org (enforced by org_id from the
authenticated session).  Another org's record returns 404 (not 403) to avoid leaking
whether the record exists.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from codeflux.api.deps import require_user
from codeflux.db.models import User
from codeflux.db.session import get_db_session
from codeflux.explain.facts import FACT_MODELS
from codeflux.explain.service import explain_arena, explain_trace, narrate

logger = logging.getLogger("codeflux.api.explain")

router = APIRouter(prefix="/api/explain", tags=["explain"])

# Arena kinds that look up ArenaRun instead of RequestTrace
_ARENA_KINDS = {"compare", "debate"}


def _resolve_kind(kind: str) -> bool:
    """Validate kind and return True if it maps to ArenaRun, False for RequestTrace."""
    if kind not in FACT_MODELS:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_kind", "message": f"Unknown explain kind: {kind!r}"},
        )
    return kind in _ARENA_KINDS


@router.get("/{kind}/{record_id}")
async def get_explain(
    kind: str,
    record_id: str,
    request: Request,
    _session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Return the deterministic plain-language explanation for a record."""
    is_arena = _resolve_kind(kind)
    org_id: str = current_user.org_id

    session_factory = request.app.state.session_factory
    if is_arena:
        result = await explain_arena(session_factory, run_id=record_id, org_id=org_id, kind=kind)
    else:
        result = await explain_trace(session_factory, trace_id=record_id, org_id=org_id, kind=kind)

    if result is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Record not found."},
        )
    return result


@router.post("/{kind}/{record_id}/narrate")
async def post_narrate(
    kind: str,
    record_id: str,
    request: Request,
    _session: Annotated[AsyncSession, Depends(get_db_session)],
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Generate (or return cached) AI narration for an explain record.

    Sends only the facts JSON to the model.  Any reply containing numbers not
    present in the facts is discarded and the deterministic text is returned
    instead.
    """
    is_arena = _resolve_kind(kind)
    org_id: str = current_user.org_id

    settings = request.app.state.settings
    narration_client = httpx.AsyncClient(timeout=30.0)

    # Use the app's own gateway as the narration back-end (loopback).
    # In tests this URL is mocked via respx.
    narration_url: str = getattr(
        settings, "narration_url", "http://localhost:8000/v1/chat/completions"
    )
    narration_key: str = getattr(settings, "narration_key", "internal")
    narration_model: str = getattr(settings, "narration_model", "gpt-4o-mini")

    try:
        result = await narrate(
            request.app.state.session_factory,
            record_id=record_id,
            org_id=org_id,
            kind=kind,
            is_arena=is_arena,
            narration_client=narration_client,
            narration_url=narration_url,
            narration_key=narration_key,
            narration_model=narration_model,
        )
    finally:
        await narration_client.aclose()

    if result.get("error") == "not_found":
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "Record not found."},
        )
    return result
