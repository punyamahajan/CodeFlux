from __future__ import annotations

from codeflux.metering.pricing import PRICE_VERSION, compute_cost, get_model_price
from codeflux.schemas import Usage


def test_pricing_table_lookup_and_default():
    p_mini = get_model_price("gpt-4o-mini")
    assert p_mini.charged_input_per_1m == 150_000
    assert p_mini.charged_output_per_1m == 600_000
    assert p_mini.is_free_tier is False

    # Prefix stripping
    p_gem = get_model_price("models/gemini-2.0-flash")
    assert p_gem.is_free_tier is True
    assert p_gem.charged_input_per_1m == 0
    assert p_gem.list_input_per_1m > 0

    # Unknown model falls back to default
    p_def = get_model_price("completely-unknown-custom-model-xyz")
    assert p_def.model == "default"
    assert p_def.charged_input_per_1m == 500_000


def test_hand_calculated_cost_cases():
    # Case 1: gpt-4o-mini
    # 1,000 prompt tokens @ $0.15/1M = 150 micro-USD
    # 500 completion tokens @ $0.60/1M = 300 micro-USD
    # Total charged = 450 micro-USD, Total list = 450 micro-USD, Savings = 0
    res_mini = compute_cost(
        Usage(prompt_tokens=1000, completion_tokens=500, total_tokens=1500),
        model="gpt-4o-mini",
    )
    assert res_mini.charged_micro == 450
    assert res_mini.list_micro == 450
    assert res_mini.savings_micro == 0
    assert res_mini.price_version == PRICE_VERSION
    assert res_mini.is_estimate is True

    # Case 2: gpt-4o
    # 10,000 prompt tokens @ $2.50/1M = 25,000 micro-USD
    # 2,000 completion tokens @ $10.00/1M = 20,000 micro-USD
    # Total charged = 45,000 micro-USD
    res_4o = compute_cost(
        {"prompt_tokens": 10_000, "completion_tokens": 2_000},
        model="gpt-4o",
    )
    assert res_4o.charged_micro == 45_000
    assert res_4o.list_micro == 45_000
    assert res_4o.savings_micro == 0

    # Case 3: Free-tier model (e.g. Groq llama-3.3-70b-versatile)
    # Charged = 0, List price > 0, Savings = list - charged
    # 1,000 prompt @ $0.59/1M = 590 micro-USD
    # 1,000 completion @ $0.79/1M = 790 micro-USD
    # List total = 1,380 micro-USD, Charged = 0, Savings = 1,380 micro-USD
    res_groq = compute_cost(
        tokens=1000,
        model="llama-3.3-70b-versatile",
        completion_tokens=1000,
    )
    assert res_groq.charged_micro == 0
    assert res_groq.list_micro == 1380
    assert res_groq.savings_micro == 1380
    assert res_groq.price_row.is_free_tier is True


def test_integer_ceiling_division_prevents_zero_loss():
    # Even 1 token with non-zero rate gets ceiling charged 1 micro-USD
    res = compute_cost(
        Usage(prompt_tokens=1, completion_tokens=0, total_tokens=1), model="gpt-4o-mini"
    )
    assert res.charged_micro == 1
    assert res.list_micro == 1
