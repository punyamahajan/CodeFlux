"""Playground API router."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from codeflux.api.deps import require_user
from codeflux.arena.service import execute_playground_chat
from codeflux.db.models import User

router = APIRouter(prefix="/api/playground", tags=["playground"])


class PlaygroundChatRequest(BaseModel):
    format: Literal["openai", "gemini"] = "openai"
    model: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    key_id: str | None = None
    session_id: str | None = None
    stream: bool = False


@router.post("/chat")
async def playground_chat(
    payload: PlaygroundChatRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Execute a chat call using the real gateway code path, billed to the selected key."""
    router_engine = request.app.state.router
    session_factory = request.app.state.session_factory

    return await execute_playground_chat(
        router=router_engine,
        session_factory=session_factory,
        org_id=current_user.org_id,
        user_email=current_user.email,
        model=payload.model,
        messages=payload.messages,
        format_type=payload.format,
        key_id=payload.key_id,
        session_id=payload.session_id,
    )
