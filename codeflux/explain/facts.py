"""Pydantic models for each explain fact kind.

Each feature that makes a decision stores a facts JSON that conforms to one of
these models.  The ``schema_version`` field is mandatory in every model and must
be incremented when fields are added or renamed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Shared types
# ---------------------------------------------------------------------------


class AttemptRecord(BaseModel):
    """One routing attempt inside a trace."""

    model_config = ConfigDict(extra="allow")

    provider: str
    model: str
    status_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None


# ---------------------------------------------------------------------------
# Trace — the core per-request facts
# ---------------------------------------------------------------------------


class TraceFacts(BaseModel):
    """Facts stored on every RequestTrace row."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    provider: str | None = None
    model: str | None = None
    status_code: int | None = None
    latency_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Routing
    attempts: list[AttemptRecord] = []
    # Session
    session_id: str | None = None
    context_carried: bool = False
    messages_sent: int = 0
    messages_trimmed: int = 0
    provider_changed: bool = False
    # Outcome — set to "blocked" when the request was refused
    outcome: str = "success"
    block_reason: str | None = None


# ---------------------------------------------------------------------------
# Cost — cost / pricing facts (sub-section of a trace)
# ---------------------------------------------------------------------------


class CostFacts(BaseModel):
    """Pricing facts stored alongside a trace."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    pricing_version: str
    charged_cost_micro: int
    list_cost_micro: int
    savings_micro: int
    is_estimate: bool
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: str


# ---------------------------------------------------------------------------
# Credits — credit-balance facts (from the ledger)
# ---------------------------------------------------------------------------


class LedgerEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    amount_micro: int
    balance_after_micro: int
    reason: str
    trace_id: str | None = None


class CreditsFacts(BaseModel):
    """Facts explaining how a key's credit balance was computed."""

    model_config = ConfigDict(extra="allow")

    schema_version: int
    key_id: str
    credit_limit_micro: int
    credit_remaining_micro: int
    entries: list[LedgerEntry] = []


# ---------------------------------------------------------------------------
# Usage — aggregate usage facts
# ---------------------------------------------------------------------------


class UsageFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_micro: int
    request_count: int
    period: str


# ---------------------------------------------------------------------------
# Blocked — a request that was refused before reaching a provider
# ---------------------------------------------------------------------------


class BlockedFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    reason: str  # "rate_limit" | "insufficient_credits" | "no_provider" | "revoked_key" | ...
    detail: str
    credits_remaining_micro: int | None = None
    rpm_limit: int | None = None
    retry_after_seconds: int | None = None


# ---------------------------------------------------------------------------
# Compare arena
# ---------------------------------------------------------------------------


class CompareModelResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    model: str
    output: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_micro: int = 0
    error: str | None = None
    # Judge scores
    accuracy: int | None = None
    clarity: int | None = None
    completeness: int | None = None
    judge_reason: str | None = None


class CompareFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    prompt_summary: str
    models: list[CompareModelResult]
    ranking: list[str]  # model names in winning order
    judge_model: str | None = None
    judge_flagged: bool = False  # True when judge reply was discarded


# ---------------------------------------------------------------------------
# Debate arena
# ---------------------------------------------------------------------------


class DebateTurn(BaseModel):
    model_config = ConfigDict(extra="allow")

    side: Literal["FOR", "AGAINST"]
    model: str
    round: int
    word_count: int
    content: str


class DebateFacts(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int
    topic: str
    model_a: str
    model_b: str
    side_a: Literal["FOR", "AGAINST"]
    side_b: Literal["FOR", "AGAINST"]
    rounds: int
    turns: list[DebateTurn] = []
    judge_model: str
    score_a: int | None = None
    score_b: int | None = None
    verdict: Literal["FOR", "AGAINST", "TIE"] | None = None
    judge_flagged: bool = False


# ---------------------------------------------------------------------------
# Dispatch table: kind string → Pydantic model
# ---------------------------------------------------------------------------

FACT_MODELS: dict[str, type[BaseModel]] = {
    "trace": TraceFacts,
    "cost": CostFacts,
    "credits": CreditsFacts,
    "usage": UsageFacts,
    "blocked": BlockedFacts,
    "compare": CompareFacts,
    "debate": DebateFacts,
}


def parse_facts(kind: str, raw: dict[str, Any]) -> BaseModel:
    """Validate *raw* against the Pydantic model for *kind*."""
    model_cls = FACT_MODELS.get(kind)
    if model_cls is None:
        raise ValueError(f"Unknown explain kind: {kind!r}")
    return model_cls.model_validate(raw)
