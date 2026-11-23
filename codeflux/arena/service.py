"""Service layer for Playground, Compare Arena, and Debate Arena."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from codeflux.db.models import ArenaRun, PlatformKey
from codeflux.gateway.normalization import (
    gemini_request,
    openai_request,
    to_gemini,
    to_openai,
)
from codeflux.gateway.router import RoutingEngine
from codeflux.metering.pricing import compute_cost
from codeflux.metering.service import record_usage_and_trace
from codeflux.schemas import GeminiRequest, Usage

logger = logging.getLogger("codeflux.arena")


# ---------------------------------------------------------------------------
# Judge Pydantic models
# ---------------------------------------------------------------------------


class CompareModelScore(BaseModel):
    accuracy: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    completeness: int = Field(ge=1, le=10)
    reason: str = ""


class CompareJudgeResult(BaseModel):
    scores: dict[str, CompareModelScore]


class DebateSideScore(BaseModel):
    argument_strength: int = Field(ge=1, le=10)
    evidence: int = Field(ge=1, le=10)
    rebuttal: int = Field(ge=1, le=10)
    reason: str = ""


class DebateJudgeResult(BaseModel):
    score_for: DebateSideScore
    score_against: DebateSideScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_key(
    session_factory: async_sessionmaker[AsyncSession],
    org_id: str,
    key_id: str | None,
) -> PlatformKey:
    """Validate that the platform key exists, belongs to the org, and has remaining credits."""
    async with session_factory() as session:
        if key_id:
            stmt = select(PlatformKey).where(PlatformKey.id == key_id, PlatformKey.org_id == org_id)
            res = await session.execute(stmt)
            key = res.scalar_one_or_none()
        else:
            stmt2 = (
                select(PlatformKey)
                .where(PlatformKey.org_id == org_id)
                .order_by(PlatformKey.created_at.desc())
            )
            res2 = await session.execute(stmt2)
            key = res2.scalars().first()

        if not key:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "no_key",
                    "message": "No active platform key found for this organization.",
                },
            )
        if key.credit_remaining_micro <= 0:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "insufficient_credits",
                    "message": "Insufficient credits remaining on platform key.",
                },
            )
        return key


# ---------------------------------------------------------------------------
# Playground
# ---------------------------------------------------------------------------


async def execute_playground_chat(
    router: RoutingEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: str,
    user_email: str,
    model: str,
    messages: list[dict[str, Any]],
    format_type: Literal["openai", "gemini"] = "openai",
    key_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Execute a single chat call using the real gateway code path."""
    key = await _resolve_key(session_factory, org_id, key_id)

    raw_req: dict[str, Any]
    if format_type == "gemini":
        gemini_contents = []
        for m in messages:
            gemini_contents.append(
                {
                    "role": "model" if m.get("role") == "assistant" else "user",
                    "parts": [{"text": m.get("content", "")}],
                }
            )
        raw_req = {"contents": gemini_contents}
        gemini_obj = GeminiRequest.model_validate(raw_req)
        normalized = gemini_request(model, gemini_obj)
    else:
        raw_req = {"model": model, "messages": messages}
        normalized = openai_request(raw_req, "chat")

    start_time = time.monotonic()
    trace_id = f"trc_{uuid.uuid4().hex[:28]}"

    try:
        result = await router.route(normalized, user_email)
    except Exception as exc:
        logger.error("Playground gateway route error: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "provider_error", "message": f"Upstream provider error: {exc}"},
        ) from exc

    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    usage = result.response.usage
    p_tokens = usage.prompt_tokens if usage else 0
    c_tokens = usage.completion_tokens if usage else 0

    trace_facts: dict[str, Any] = {
        "attempts": getattr(result, "attempt_records", None) or [],
        "session_id": session_id,
        "format": format_type,
    }

    await record_usage_and_trace(
        session_factory,
        org_id=org_id,
        key_id=key.id,
        provider=result.provider,
        model=model,
        status_code=200,
        latency_ms=elapsed_ms,
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        trace_id=trace_id,
        facts=trace_facts,
    )

    if format_type == "gemini":
        raw_resp = to_gemini(result.response)
    else:
        raw_resp = to_openai(result.response, "chat", model)

    return {
        "reply": result.response.content or "",
        "raw_request": raw_req,
        "raw_response": raw_resp,
        "latency_ms": elapsed_ms,
        "tokens": {
            "prompt_tokens": p_tokens,
            "completion_tokens": c_tokens,
            "total_tokens": p_tokens + c_tokens,
        },
        "trace_id": trace_id,
        "provider": result.provider,
    }


# ---------------------------------------------------------------------------
# Compare Arena
# ---------------------------------------------------------------------------


async def execute_compare_arena(
    router: RoutingEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: str,
    user_email: str,
    prompt: str,
    models: list[str],
    judge: bool = False,
    judge_model: str | None = None,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Run up to 4 models in parallel with no fallback, score them, and rank them."""
    if not models or len(models) > 4:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_models",
                "message": "Specify between 1 and 4 models to compare.",
            },
        )

    key = await _resolve_key(session_factory, org_id, key_id)
    run_id = f"arn_{uuid.uuid4().hex[:28]}"

    async def _call_model(model_name: str) -> dict[str, Any]:
        req_payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
        }
        normalized = openai_request(req_payload, "chat")
        m_start = time.monotonic()
        try:
            # Force no fallback for raw models, but allow routes to use their configured candidate chain
            route_kwargs = (
                {"custom_fallback": model_name} if model_name not in router.config.routes else {}
            )
            res = await router.route(
                normalized,
                user_email,
                **route_kwargs,
            )
            m_elapsed = int((time.monotonic() - m_start) * 1000)
            u = res.response.usage
            pt = u.prompt_tokens if u else 0
            ct = u.completion_tokens if u else 0
            cost_res = compute_cost(
                Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct), model_name
            )
            content = res.response.content or ""
            return {
                "provider": res.provider,
                "model": model_name,
                "output": content,
                "latency_ms": m_elapsed,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "character_count": len(content),
                "cost_micro": cost_res.charged_micro,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            m_elapsed = int((time.monotonic() - m_start) * 1000)
            logger.warning("Compare model %s failed: %s", model_name, exc)
            return {
                "provider": "unknown",
                "model": model_name,
                "output": None,
                "latency_ms": m_elapsed,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "character_count": 0,
                "cost_micro": 0,
                "error": str(exc),
            }

    # Run all models in parallel; keep partial results
    results = await asyncio.gather(*[_call_model(m) for m in models])
    model_results: list[dict[str, Any]] = list(results)

    # Judge evaluation if requested
    judge_flagged = False
    effective_judge_model = judge_model or "gpt-4o-mini"
    if judge:
        candidates_to_judge = [m for m in model_results if m["error"] is None and m["output"]]
        if candidates_to_judge:
            judge_rubric_prompt = (
                "You are an impartial AI judge. Evaluate each model's output for accuracy, clarity, and completeness. "
                "Score each dimension from 1 to 10 (integer) and give a 1-sentence reason. "
                "Output strictly a JSON object with this shape:\n"
                "{\n"
                '  "scores": {\n'
                '    "<model_name>": {"accuracy": 8, "clarity": 9, "completeness": 7, "reason": "Good explanation."}\n'
                "  }\n"
                "}\n\n"
                f"Prompt: {prompt}\n\n"
            )
            for m in candidates_to_judge:
                judge_rubric_prompt += f"--- Model: {m['model']} ---\n{m['output']}\n\n"

            eval_res = await _call_judge_with_retry(
                router,
                user_email,
                effective_judge_model,
                judge_rubric_prompt,
                CompareJudgeResult,
            )
            if eval_res is None:
                judge_flagged = True
            else:
                for m in model_results:
                    if m["model"] in eval_res.scores:
                        sc = eval_res.scores[m["model"]]
                        m["accuracy"] = sc.accuracy
                        m["clarity"] = sc.clarity
                        m["completeness"] = sc.completeness
                        m["judge_reason"] = sc.reason
                        m["judge_label"] = "AI-judged"
        else:
            judge_flagged = True

    # Compute ranking in code from scores; cost & latency as tie-breaks
    def sort_key(m: dict[str, Any]) -> tuple[int, int, int, int]:
        has_error = 1 if m["error"] else 0
        acc = m.get("accuracy") or 0
        cla = m.get("clarity") or 0
        cmp = m.get("completeness") or 0
        total_score = acc + cla + cmp
        # Sort order: error last (has_error=0 first), total_score desc, cost_micro asc, latency_ms asc
        return (has_error, -total_score, m["cost_micro"], m["latency_ms"] or 999999)

    ranked_models = sorted(model_results, key=sort_key)
    ranking = [m["model"] for m in ranked_models if not m["error"]]

    # Build facts & write traces/runs
    compare_facts = {
        "schema_version": 1,
        "prompt_summary": prompt[:100],
        "models": model_results,
        "ranking": ranking,
        "judge_model": effective_judge_model if judge else None,
        "judge_flagged": judge_flagged,
    }

    # Record trace & arena run
    total_p_tokens = sum(m["prompt_tokens"] for m in model_results)
    total_c_tokens = sum(m["completion_tokens"] for m in model_results)

    await record_usage_and_trace(
        session_factory,
        org_id=org_id,
        key_id=key.id,
        provider="arena",
        model=f"compare:{len(models)}",
        status_code=200,
        latency_ms=max((m["latency_ms"] or 0) for m in model_results) if model_results else 0,
        prompt_tokens=total_p_tokens,
        completion_tokens=total_c_tokens,
        trace_id=f"trc_{run_id[4:]}",
        facts=compare_facts,
    )

    async with session_factory() as session:
        arena_run = ArenaRun(
            id=run_id,
            org_id=org_id,
            key_id=key.id,
            kind="compare",
            facts=compare_facts,
        )
        session.add(arena_run)
        await session.commit()

    return {
        "run_id": run_id,
        "prompt": prompt,
        "models": model_results,
        "ranking": ranking,
        "judge_model": effective_judge_model if judge else None,
        "judge_flagged": judge_flagged,
    }


# ---------------------------------------------------------------------------
# Debate Arena
# ---------------------------------------------------------------------------


async def execute_debate_arena(
    router: RoutingEngine,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: str,
    user_email: str,
    topic: str,
    model_a: str,
    model_b: str,
    judge_model: str | None = None,
    rounds: int = 2,
    key_id: str | None = None,
) -> dict[str, Any]:
    """Run sequential debate turns with word and token limits, followed by AI judging."""
    effective_rounds = min(max(1, rounds), 3)  # default 2, max 3
    key = await _resolve_key(session_factory, org_id, key_id)
    run_id = f"arn_{uuid.uuid4().hex[:28]}"

    transcript: list[dict[str, Any]] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_cost_micro = 0
    TOKEN_CAP = 4000

    side_a = "FOR"
    side_b = "AGAINST"

    turns_facts: list[dict[str, Any]] = []

    for r in range(1, effective_rounds + 1):
        # Check token cap
        if (total_prompt_tokens + total_completion_tokens) >= TOKEN_CAP:
            break

        # Turn FOR (Model A)
        turn_for = await _run_debate_turn(
            router,
            user_email,
            model=model_a,
            side="FOR",
            topic=topic,
            current_round=r,
            total_rounds=effective_rounds,
            transcript=transcript,
        )
        total_prompt_tokens += turn_for["prompt_tokens"]
        total_completion_tokens += turn_for["completion_tokens"]
        total_cost_micro += turn_for["cost_micro"]
        turns_facts.append(
            {
                "side": "FOR",
                "model": model_a,
                "round": r,
                "word_count": turn_for["word_count"],
                "content": turn_for["content"],
            }
        )
        transcript.append(
            {"role": "user", "content": f"[Round {r} - FOR ({model_a})]: {turn_for['content']}"}
        )

        if (total_prompt_tokens + total_completion_tokens) >= TOKEN_CAP:
            break

        # Turn AGAINST (Model B)
        turn_against = await _run_debate_turn(
            router,
            user_email,
            model=model_b,
            side="AGAINST",
            topic=topic,
            current_round=r,
            total_rounds=effective_rounds,
            transcript=transcript,
        )
        total_prompt_tokens += turn_against["prompt_tokens"]
        total_completion_tokens += turn_against["completion_tokens"]
        total_cost_micro += turn_against["cost_micro"]
        turns_facts.append(
            {
                "side": "AGAINST",
                "model": model_b,
                "round": r,
                "word_count": turn_against["word_count"],
                "content": turn_against["content"],
            }
        )
        transcript.append(
            {
                "role": "user",
                "content": f"[Round {r} - AGAINST ({model_b})]: {turn_against['content']}",
            }
        )

    # Judging
    effective_judge_model = judge_model or "gpt-4o-mini"
    judge_prompt = (
        "You are an impartial judge scoring a formal debate.\n"
        f"Topic: {topic}\n"
        f"FOR side: {model_a}\n"
        f"AGAINST side: {model_b}\n\n"
        "Transcript:\n"
    )
    for t in turns_facts:
        judge_prompt += f"[{t['side']} - Round {t['round']}]: {t['content']}\n\n"

    judge_prompt += (
        "Score each side on: argument_strength (1-10), evidence (1-10), rebuttal (1-10). "
        "Output strictly a JSON object with this shape:\n"
        "{\n"
        '  "score_for": {"argument_strength": 8, "evidence": 7, "rebuttal": 8, "reason": "Strong points."},\n'
        '  "score_against": {"argument_strength": 7, "evidence": 6, "rebuttal": 7, "reason": "Good rebuttals."}\n'
        "}\n"
    )

    judge_res = await _call_judge_with_retry(
        router,
        user_email,
        effective_judge_model,
        judge_prompt,
        DebateJudgeResult,
    )

    score_a = None
    score_b = None
    judge_flagged = False
    verdict: Literal["FOR", "AGAINST", "TIE"] = "TIE"

    if judge_res is None:
        judge_flagged = True
        # Graceful fallback: verdict based on content length
        words_for = sum(t["word_count"] for t in turns_facts if t["side"] == "FOR")
        words_against = sum(t["word_count"] for t in turns_facts if t["side"] == "AGAINST")
        if words_for > words_against:
            verdict = "FOR"
        elif words_against > words_for:
            verdict = "AGAINST"
        else:
            verdict = "TIE"
    else:
        tot_a = (
            judge_res.score_for.argument_strength
            + judge_res.score_for.evidence
            + judge_res.score_for.rebuttal
        )
        tot_b = (
            judge_res.score_against.argument_strength
            + judge_res.score_against.evidence
            + judge_res.score_against.rebuttal
        )
        score_a = tot_a
        score_b = tot_b
        if tot_a > tot_b:
            verdict = "FOR"
        elif tot_b > tot_a:
            verdict = "AGAINST"
        else:
            verdict = "TIE"

    debate_facts = {
        "schema_version": 1,
        "topic": topic,
        "model_a": model_a,
        "model_b": model_b,
        "side_a": side_a,
        "side_b": side_b,
        "rounds": effective_rounds,
        "turns": turns_facts,
        "judge_model": effective_judge_model,
        "score_a": score_a,
        "score_b": score_b,
        "verdict": verdict,
        "judge_flagged": judge_flagged,
    }

    # Record trace & arena run
    await record_usage_and_trace(
        session_factory,
        org_id=org_id,
        key_id=key.id,
        provider="arena",
        model=f"debate:{model_a}_vs_{model_b}",
        status_code=200,
        latency_ms=1000,
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        trace_id=f"trc_{run_id[4:]}",
        facts=debate_facts,
    )

    async with session_factory() as session:
        arena_run = ArenaRun(
            id=run_id,
            org_id=org_id,
            key_id=key.id,
            kind="debate",
            facts=debate_facts,
        )
        session.add(arena_run)
        await session.commit()

    return {
        "run_id": run_id,
        "topic": topic,
        "model_a": model_a,
        "model_b": model_b,
        "side_a": side_a,
        "side_b": side_b,
        "rounds": effective_rounds,
        "turns": turns_facts,
        "judge_model": effective_judge_model,
        "score_a": score_a,
        "score_b": score_b,
        "verdict": verdict,
        "judge_flagged": judge_flagged,
    }


async def _run_debate_turn(
    router: RoutingEngine,
    user_email: str,
    *,
    model: str,
    side: str,
    topic: str,
    current_round: int,
    total_rounds: int,
    transcript: list[dict[str, Any]],
) -> dict[str, Any]:
    sys_prompt = (
        f"You are participating in a formal Oxford-style debate.\n"
        f"Topic: {topic}\n"
        f"Your assigned stance is: {side}.\n"
        f"Round {current_round} of {total_rounds}.\n"
        "RULES: Keep your turn concise and under 120 words. Focus strictly on persuasive arguments and evidence."
    )
    messages = [{"role": "system", "content": sys_prompt}]
    messages.extend(transcript)
    messages.append(
        {
            "role": "user",
            "content": f"Deliver your round {current_round} argument supporting {side}. Limit to 120 words.",
        }
    )

    req = openai_request({"model": model, "messages": messages}, "chat")
    try:
        route_kwargs = {"custom_fallback": model} if model not in router.config.routes else {}
        res = await router.route(req, user_email, **route_kwargs)
        content = res.response.content or ""
        # Cap strictly at 120 words
        words = content.split()
        if len(words) > 120:
            content = " ".join(words[:120])
        u = res.response.usage
        pt = u.prompt_tokens if u else 0
        ct = u.completion_tokens if u else 0
        cost_res = compute_cost(
            Usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct), model
        )
        return {
            "content": content,
            "word_count": len(content.split()),
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "cost_micro": cost_res.charged_micro,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Debate turn failed for model %s: %s", model, exc)
        return {
            "content": f"[{model} was unable to respond: {exc}]",
            "word_count": 8,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_micro": 0,
        }


async def _call_judge_with_retry[T: BaseModel](
    router: RoutingEngine,
    user_email: str,
    judge_model: str,
    prompt: str,
    schema_cls: type[T],
) -> T | None:
    """Call the judge model with 1 retry on invalid JSON / validation failure."""
    for attempt in range(2):
        try:
            req = openai_request(
                {
                    "model": judge_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are an automated evaluation judge. Return only valid JSON adhering to the specified schema.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
                "chat",
            )
            route_kwargs = (
                {"custom_fallback": judge_model} if judge_model not in router.config.routes else {}
            )
            res = await router.route(req, user_email, **route_kwargs)
            text = (res.response.content or "").strip()
            # Clean possible markdown fence
            if text.startswith("```"):
                text = text.strip("`")
                text = text.removeprefix("json")
                text = text.strip()
            data = json.loads(text)
            return schema_cls.model_validate(data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Judge attempt %d failed: %s", attempt + 1, exc)
            if attempt == 0:
                await asyncio.sleep(0.5)
    return None
