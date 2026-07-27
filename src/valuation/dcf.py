"""Explicit-assumption free-cash-flow DCF with sensitivity analysis."""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class DCFInputs:
    base_free_cash_flow: float
    cash: float
    debt: float
    shares_outstanding: float
    discount_rate: float
    near_term_growth_rate: float
    terminal_growth_rate: float
    projection_years: int = 5


def _value_per_share(inputs: DCFInputs, discount_rate: float, growth_rate: float, terminal_rate: float) -> float | None:
    if (
        inputs.base_free_cash_flow <= 0
        or inputs.shares_outstanding <= 0
        or not 1 <= inputs.projection_years <= 20
        or discount_rate <= terminal_rate
        or discount_rate <= -1
        or growth_rate <= -1
        or terminal_rate <= -1
    ):
        return None

    projected = []
    for year in range(1, inputs.projection_years + 1):
        cash_flow = inputs.base_free_cash_flow * ((1 + growth_rate) ** year)
        projected.append(cash_flow / ((1 + discount_rate) ** year))
    final_cash_flow = inputs.base_free_cash_flow * ((1 + growth_rate) ** inputs.projection_years)
    terminal_value = final_cash_flow * (1 + terminal_rate) / (discount_rate - terminal_rate)
    enterprise_value = sum(projected) + terminal_value / ((1 + discount_rate) ** inputs.projection_years)
    equity_value = enterprise_value + inputs.cash - inputs.debt
    return max(0.0, equity_value / inputs.shares_outstanding)


def discounted_cash_flow(inputs: DCFInputs, sensitivity_step: float = 0.01) -> dict:
    """Return bear/base/bull plus a 3x3 discount/growth sensitivity grid."""
    base = _value_per_share(
        inputs,
        inputs.discount_rate,
        inputs.near_term_growth_rate,
        inputs.terminal_growth_rate,
    )
    if base is None:
        return {"bear": None, "base": None, "bull": None, "conservative": None, "grid": {}}

    bear = _value_per_share(
        inputs,
        inputs.discount_rate + sensitivity_step,
        inputs.near_term_growth_rate - sensitivity_step,
        inputs.terminal_growth_rate - sensitivity_step,
    )
    bull = _value_per_share(
        inputs,
        inputs.discount_rate - sensitivity_step,
        inputs.near_term_growth_rate + sensitivity_step,
        inputs.terminal_growth_rate + sensitivity_step,
    )
    grid: dict[str, float | None] = {}
    for discount_delta in (-sensitivity_step, 0.0, sensitivity_step):
        for growth_delta in (-sensitivity_step, 0.0, sensitivity_step):
            key = f"discount_{inputs.discount_rate + discount_delta:.4f}__growth_{inputs.near_term_growth_rate + growth_delta:.4f}"
            grid[key] = _value_per_share(
                inputs,
                inputs.discount_rate + discount_delta,
                inputs.near_term_growth_rate + growth_delta,
                inputs.terminal_growth_rate,
            )
    return {
        "bear": bear,
        "base": base,
        "bull": bull,
        "conservative": bear,
        "grid": grid,
        "inputs": dataclasses.asdict(inputs),
    }
