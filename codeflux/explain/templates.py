"""Deterministic plain-language templates for each explain kind.

Each function accepts the validated Pydantic facts object and returns a dict
with keys ``headline`` (str) and ``bullets`` (list[str]).  Templates never
invent numbers — every number in the output must come from the facts object.
"""

from __future__ import annotations

from pydantic import BaseModel

from codeflux.explain.facts import (
    BlockedFacts,
    CompareFacts,
    CostFacts,
    CreditsFacts,
    DebateFacts,
    TraceFacts,
    UsageFacts,
)


def _micro_usd(micro: int) -> str:
    """Format micro-USD as a readable dollar string."""
    return f"${micro / 1_000_000:.6f}"


# ---------------------------------------------------------------------------


def render_trace(facts: TraceFacts) -> dict[str, object]:
    bullets: list[str] = []

    if facts.attempts:
        successful = [a for a in facts.attempts if not a.skipped and (a.error is None)]
        failed = [a for a in facts.attempts if a.error is not None and not a.skipped]
        skipped = [a for a in facts.attempts if a.skipped]

        if skipped:
            for a in skipped:
                bullets.append(
                    f"Candidate {a.provider}/{a.model} was skipped"
                    + (f": {a.skip_reason}" if a.skip_reason else ".")
                )
        if failed:
            bullets.append(f"A fallback occurred: {len(failed)} provider(s) failed before success.")
            for a in failed:
                bullets.append(
                    f"  • {a.provider}/{a.model} returned"
                    f" {'HTTP ' + str(a.status_code) if a.status_code else a.error or 'an error'}."
                )
        if successful:
            win = successful[-1]
            bullets.append(f"Request succeeded via {win.provider}/{win.model}.")
    else:
        if facts.provider:
            bullets.append(f"Request routed to {facts.provider}/{facts.model}.")

    if facts.latency_ms is not None:
        bullets.append(f"End-to-end latency: {facts.latency_ms} ms.")

    if facts.session_id:
        bullets.append(f"Session {facts.session_id} was active.")
        if facts.context_carried:
            bullets.append(
                f"Context carried forward: {facts.messages_sent} message(s) sent"
                + (
                    f", {facts.messages_trimmed} older message(s) trimmed to stay within limits."
                    if facts.messages_trimmed
                    else "."
                )
            )
        if facts.provider_changed:
            bullets.append("The provider changed from the previous session turn due to fallback.")

    if facts.outcome == "blocked":
        bullets.append(f"Request was blocked: {facts.block_reason or 'unknown reason'}.")

    headline = (
        f"Request {'blocked' if facts.outcome == 'blocked' else 'succeeded'}"
        + (f" via {facts.provider}/{facts.model}" if facts.provider else "")
        + "."
    )
    return {"headline": headline, "bullets": bullets, "facts": facts.model_dump()}


def render_cost(facts: CostFacts) -> dict[str, object]:
    bullets: list[str] = [
        f"Model: {facts.model} (pricing version {facts.pricing_version}).",
        (
            f"Tokens used: {facts.prompt_tokens} prompt + {facts.completion_tokens} completion"
            f" = {facts.total_tokens} total."
        ),
        f"List price: {_micro_usd(facts.list_cost_micro)}.",
        f"Charged: {_micro_usd(facts.charged_cost_micro)}.",
    ]
    if facts.savings_micro > 0:
        bullets.append(f"Savings applied: {_micro_usd(facts.savings_micro)}.")
    if facts.is_estimate:
        bullets.append("Cost is an estimate based on a static price table.")
    return {
        "headline": f"Cost for this request: {_micro_usd(facts.charged_cost_micro)}.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


def render_credits(facts: CreditsFacts) -> dict[str, object]:
    bullets: list[str] = [
        f"Credit limit: {_micro_usd(facts.credit_limit_micro)}.",
        f"Credits remaining: {_micro_usd(facts.credit_remaining_micro)}.",
    ]
    if facts.entries:
        bullets.append(f"Ledger has {len(facts.entries)} entries:")
        for e in facts.entries:
            sign = "+" if e.amount_micro >= 0 else ""
            bullets.append(
                f"  • {sign}{_micro_usd(e.amount_micro)} ({e.reason})"
                f" → balance {_micro_usd(e.balance_after_micro)}."
            )
    return {
        "headline": f"Credits remaining: {_micro_usd(facts.credit_remaining_micro)}.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


def render_usage(facts: UsageFacts) -> dict[str, object]:
    bullets: list[str] = [
        f"Period: {facts.period}.",
        f"Requests: {facts.request_count}.",
        (
            f"Tokens: {facts.prompt_tokens} prompt + {facts.completion_tokens} completion"
            f" = {facts.total_tokens} total."
        ),
        f"Total cost: {_micro_usd(facts.cost_micro)}.",
    ]
    return {
        "headline": f"Usage summary for period {facts.period}.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


def render_blocked(facts: BlockedFacts) -> dict[str, object]:
    bullets: list[str] = [f"Block reason: {facts.reason}.", f"Detail: {facts.detail}"]
    if facts.credits_remaining_micro is not None:
        bullets.append(
            f"Credits remaining at time of block: {_micro_usd(facts.credits_remaining_micro)}."
        )
    if facts.rpm_limit is not None:
        bullets.append(f"Rate limit: {facts.rpm_limit} requests per minute.")
    if facts.retry_after_seconds is not None:
        bullets.append(f"Retry after: {facts.retry_after_seconds} second(s).")
    return {
        "headline": f"Request blocked: {facts.reason}.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


def render_compare(facts: CompareFacts) -> dict[str, object]:
    bullets: list[str] = [f"Prompt: {facts.prompt_summary}"]
    for m in facts.models:
        status = m.error or "success"
        cost_str = _micro_usd(m.cost_micro)
        bullets.append(
            f"  • {m.provider}/{m.model}: {status}"
            + (f", {m.latency_ms} ms" if m.latency_ms is not None else "")
            + f", cost {cost_str}"
            + (
                f", judge scores accuracy={m.accuracy} clarity={m.clarity}"
                f" completeness={m.completeness}"
                if m.accuracy is not None
                else ""
            )
            + "."
        )
    if facts.ranking:
        bullets.append(f"Ranking: {', '.join(facts.ranking)}.")
    if facts.judge_flagged:
        bullets.append(
            "Judge reply was discarded (contained invented numbers); ranking based on cost/latency only."
        )
    return {
        "headline": f"Compare arena: {len(facts.models)} model(s) evaluated.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


def render_debate(facts: DebateFacts) -> dict[str, object]:
    bullets: list[str] = [
        f"Topic: {facts.topic}",
        f"FOR: {facts.model_a} ({facts.side_a}), AGAINST: {facts.model_b} ({facts.side_b}).",
        f"Rounds: {facts.rounds}.",
    ]
    if facts.score_a is not None and facts.score_b is not None:
        bullets.append(
            f"Score — {facts.model_a}: {facts.score_a}, {facts.model_b}: {facts.score_b}."
        )
    if facts.verdict:
        bullets.append(f"Verdict: {facts.verdict}.")
    if facts.judge_flagged:
        bullets.append("Judge reply was discarded; verdict computed from token counts.")
    return {
        "headline": f"Debate arena verdict: {facts.verdict or 'pending'}.",
        "bullets": bullets,
        "facts": facts.model_dump(),
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_RENDERERS = {
    "trace": render_trace,
    "cost": render_cost,
    "credits": render_credits,
    "usage": render_usage,
    "blocked": render_blocked,
    "compare": render_compare,
    "debate": render_debate,
}


def render(kind: str, facts: BaseModel) -> dict[str, object]:
    """Dispatch to the right renderer and return ``{headline, bullets, facts}``."""
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        raise ValueError(f"No template for kind {kind!r}")
    return renderer(facts)  # type: ignore[arg-type]
