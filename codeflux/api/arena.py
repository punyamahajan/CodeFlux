"""Arenas API router: Compare Arena and Debate Arena."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from codeflux.api.deps import require_user
from codeflux.arena.service import execute_compare_arena, execute_debate_arena
from codeflux.db.models import User

router = APIRouter(prefix="/api/arena", tags=["arena"])


class CompareRequest(BaseModel):
    prompt: str
    models: list[str] = Field(min_length=1, max_length=4)
    judge: bool = False
    judge_model: str | None = None
    key_id: str | None = None


class DebateRequest(BaseModel):
    topic: str
    model_a: str
    model_b: str
    judge_model: str | None = None
    rounds: int = 2
    key_id: str | None = None


@router.post("/compare")
async def arena_compare(
    payload: CompareRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Run up to 4 models in parallel with no fallback, score them, and rank them."""
    router_engine = request.app.state.router
    session_factory = request.app.state.session_factory

    return await execute_compare_arena(
        router=router_engine,
        session_factory=session_factory,
        org_id=current_user.org_id,
        user_email=current_user.email,
        prompt=payload.prompt,
        models=payload.models,
        judge=payload.judge,
        judge_model=payload.judge_model,
        key_id=payload.key_id,
    )


@router.post("/debate")
async def arena_debate(
    payload: DebateRequest,
    request: Request,
    current_user: Annotated[User, Depends(require_user)],
) -> dict[str, Any]:
    """Run an Oxford-style debate across multiple rounds with word caps and AI judging."""
    router_engine = request.app.state.router
    session_factory = request.app.state.session_factory

    return await execute_debate_arena(
        router=router_engine,
        session_factory=session_factory,
        org_id=current_user.org_id,
        user_email=current_user.email,
        topic=payload.topic,
        model_a=payload.model_a,
        model_b=payload.model_b,
        judge_model=payload.judge_model,
        rounds=payload.rounds,
        key_id=payload.key_id,
    )
