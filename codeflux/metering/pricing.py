from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from codeflux.schemas import Usage

PRICE_VERSION = "2026-03-01"


@dataclass(frozen=True)
class ModelPrice:
    """Pricing configuration for a model in integer micro-USD per 1M tokens.

    1 USD = 1,000,000 micro-USD.
    All figures are estimates.
    """

    model: str
    charged_input_per_1m: int
    charged_output_per_1m: int
    list_input_per_1m: int
    list_output_per_1m: int
    is_free_tier: bool = False
    description: str = "Estimated pricing"
    context_budget: int = 6000


# Known model pricing table (micro-USD per 1,000,000 tokens)
PRICING_TABLE: dict[str, ModelPrice] = {
    # OpenAI Models
    "gpt-4o-mini": ModelPrice(
        model="gpt-4o-mini",
        charged_input_per_1m=150_000,  # $0.15 / 1M
        charged_output_per_1m=600_000,  # $0.60 / 1M
        list_input_per_1m=150_000,
        list_output_per_1m=600_000,
        is_free_tier=False,
    ),
    "gpt-4o": ModelPrice(
        model="gpt-4o",
        charged_input_per_1m=2_500_000,  # $2.50 / 1M
        charged_output_per_1m=10_000_000,  # $10.00 / 1M
        list_input_per_1m=2_500_000,
        list_output_per_1m=10_000_000,
        is_free_tier=False,
    ),
    "text-embedding-3-small": ModelPrice(
        model="text-embedding-3-small",
        charged_input_per_1m=20_000,  # $0.02 / 1M
        charged_output_per_1m=0,
        list_input_per_1m=20_000,
        list_output_per_1m=0,
        is_free_tier=False,
    ),
    # Groq Models (Free tier subsidized on platform; list prices show market value)
    "llama-3.3-70b-versatile": ModelPrice(
        model="llama-3.3-70b-versatile",
        charged_input_per_1m=0,  # Free tier
        charged_output_per_1m=0,
        list_input_per_1m=590_000,  # $0.59 / 1M list price
        list_output_per_1m=790_000,  # $0.79 / 1M list price
        is_free_tier=True,
    ),
    "qwen/qwen3.8-27b": ModelPrice(
        model="qwen/qwen3.8-27b",
        charged_input_per_1m=0,
        charged_output_per_1m=0,
        list_input_per_1m=200_000,
        list_output_per_1m=600_000,
        is_free_tier=True,
    ),
    # Gemini Models (Free tier subsidized on platform; list prices show market value)
    "gemini-2.0-flash": ModelPrice(
        model="gemini-2.0-flash",
        charged_input_per_1m=0,
        charged_output_per_1m=0,
        list_input_per_1m=100_000,  # $0.10 / 1M list price
        list_output_per_1m=400_000,  # $0.40 / 1M list price
        is_free_tier=True,
    ),
    "gemini-2.5-flash": ModelPrice(
        model="gemini-2.5-flash",
        charged_input_per_1m=0,
        charged_output_per_1m=0,
        list_input_per_1m=150_000,
        list_output_per_1m=600_000,
        is_free_tier=True,
    ),
    "gemini-3.1-flash-lite": ModelPrice(
        model="gemini-3.1-flash-lite",
        charged_input_per_1m=0,
        charged_output_per_1m=0,
        list_input_per_1m=75_000,
        list_output_per_1m=300_000,
        is_free_tier=True,
    ),
    "gemini-flash-latest": ModelPrice(
        model="gemini-flash-latest",
        charged_input_per_1m=0,
        charged_output_per_1m=0,
        list_input_per_1m=150_000,
        list_output_per_1m=600_000,
        is_free_tier=True,
    ),
    # Default fallback pricing
    "default": ModelPrice(
        model="default",
        charged_input_per_1m=500_000,  # $0.50 / 1M
        charged_output_per_1m=1_500_000,  # $1.50 / 1M
        list_input_per_1m=500_000,
        list_output_per_1m=1_500_000,
        is_free_tier=False,
    ),
}


@dataclass(frozen=True)
class CostResult:
    """Calculated cost for a request in integer micro-USD."""

    charged_micro: int
    list_micro: int
    price_version: str
    price_row: ModelPrice
    is_estimate: bool = True

    @property
    def savings_micro(self) -> int:
        return max(0, self.list_micro - self.charged_micro)

    def to_dict(self) -> dict[str, Any]:
        return {
            "charged_micro": self.charged_micro,
            "list_micro": self.list_micro,
            "savings_micro": self.savings_micro,
            "price_version": self.price_version,
            "is_estimate": self.is_estimate,
            "model": self.price_row.model,
            "is_free_tier": self.price_row.is_free_tier,
        }


def get_model_price(model: str) -> ModelPrice:
    """Find pricing for a model or return default pricing."""
    clean_model = model.lower()
    clean_model = clean_model.removeprefix("models/")

    # Direct match
    if clean_model in PRICING_TABLE:
        return PRICING_TABLE[clean_model]

    # Partial / prefix match
    for name, price in PRICING_TABLE.items():
        if name in clean_model or clean_model in name:
            return price

    return PRICING_TABLE["default"]


def get_context_budget(model: str) -> int:
    """Get the context token budget for a model (default 6000)."""
    price = get_model_price(model)
    return getattr(price, "context_budget", 6000)


def compute_cost(
    tokens: Usage | dict[str, int] | int,
    model: str,
    completion_tokens: int | None = None,
) -> CostResult:
    """Compute charged cost and list cost in integer micro-USD.

    No floats for money. All calculations use integer ceiling division so fractional
    micro-USD amounts round up to the nearest integer micro-USD.
    """
    if isinstance(tokens, Usage):
        prompt_cnt = tokens.prompt_tokens
        comp_cnt = tokens.completion_tokens
    elif isinstance(tokens, dict):
        prompt_cnt = tokens.get("prompt_tokens", 0)
        comp_cnt = tokens.get("completion_tokens", 0)
    else:
        prompt_cnt = int(tokens)
        comp_cnt = int(completion_tokens or 0)

    price = get_model_price(model)

    # Ceiling integer arithmetic: (tokens * rate + 999_999) // 1_000_000
    if prompt_cnt > 0 and price.charged_input_per_1m > 0:
        charged_in = (prompt_cnt * price.charged_input_per_1m + 999_999) // 1_000_000
    else:
        charged_in = 0

    if comp_cnt > 0 and price.charged_output_per_1m > 0:
        charged_out = (comp_cnt * price.charged_output_per_1m + 999_999) // 1_000_000
    else:
        charged_out = 0

    charged_total = charged_in + charged_out

    if prompt_cnt > 0 and price.list_input_per_1m > 0:
        list_in = (prompt_cnt * price.list_input_per_1m + 999_999) // 1_000_000
    else:
        list_in = 0

    if comp_cnt > 0 and price.list_output_per_1m > 0:
        list_out = (comp_cnt * price.list_output_per_1m + 999_999) // 1_000_000
    else:
        list_out = 0

    list_total = list_in + list_out

    return CostResult(
        charged_micro=charged_total,
        list_micro=list_total,
        price_version=PRICE_VERSION,
        price_row=price,
        is_estimate=True,
    )
