"""Deterministic metrics from sector-specific disclosed filing facts."""
from __future__ import annotations


def _ratio_percent(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator * 100.0


def _reported_percent(value: float | None) -> float | None:
    if value is None:
        return None
    # XBRL ratio facts are normally decimals, while some issuer exports
    # contain already-percent values. Normalize both without inventing a
    # value. Values above 100% remain valid for metrics such as LCR, but
    # the prudential ratios handled here are conventionally below 100%.
    return value * 100.0 if abs(value) <= 1.0 else value


def compute_bank_metrics(
    current: dict[str, float],
    previous: dict[str, float] | None = None,
    *,
    annual: bool,
) -> dict[str, tuple[float, str]]:
    """Compute NPL/NIM/CAR/LDR/CASA only from disclosed inputs."""
    previous = previous or {}
    metrics: dict[str, tuple[float, str]] = {}

    npl_gross = _reported_percent(current.get("npl_gross_ratio_reported"))
    if npl_gross is None:
        npl_gross = _ratio_percent(current.get("non_performing_loans_gross"), current.get("gross_loans"))
    npl_net = _reported_percent(current.get("npl_net_ratio_reported"))
    if npl_net is None:
        npl_net = _ratio_percent(current.get("non_performing_loans_net"), current.get("gross_loans"))

    nim = _reported_percent(current.get("net_interest_margin_reported"))
    if nim is None and annual:
        current_assets = current.get("earning_assets")
        previous_assets = previous.get("earning_assets")
        average_assets = (
            (current_assets + previous_assets) / 2
            if current_assets is not None and previous_assets is not None
            else None
        )
        nim = _ratio_percent(current.get("net_interest_income"), average_assets)

    car = _reported_percent(current.get("capital_adequacy_ratio_reported"))
    if car is None:
        car = _ratio_percent(current.get("regulatory_capital"), current.get("risk_weighted_assets"))

    ldr = _ratio_percent(current.get("gross_loans"), current.get("customer_deposits"))
    casa = _ratio_percent(
        (current.get("current_accounts", 0.0) + current.get("savings_accounts", 0.0))
        if "current_accounts" in current and "savings_accounts" in current
        else None,
        current.get("customer_deposits"),
    )

    for name, value in {
        "npl_gross_pct": npl_gross,
        "npl_net_pct": npl_net,
        "net_interest_margin_pct": nim,
        "capital_adequacy_ratio_pct": car,
        "loan_to_deposit_ratio_pct": ldr,
        "casa_ratio_pct": casa,
    }.items():
        if value is not None:
            metrics[name] = (value, "percent")
    return metrics


def compute_mining_metrics(
    current: dict[str, float],
    units: dict[str, str] | None = None,
) -> dict[str, tuple[float, str]]:
    """Compute reserve life and preserve explicitly disclosed operating KPIs."""
    units = units or {}
    metrics: dict[str, tuple[float, str]] = {}
    reserves = current.get("proven_probable_reserves")
    production = current.get("annual_production")
    reserve_unit = units.get("proven_probable_reserves")
    production_unit = units.get("annual_production")
    if (
        reserves is not None
        and production is not None
        and reserves >= 0
        and production > 0
        and reserve_unit
        and reserve_unit == production_unit
    ):
        metrics["reserve_life_years"] = (reserves / production, "years")

    cash_cost = current.get("cash_cost_per_unit_reported")
    if cash_cost is not None:
        metrics["cash_cost_per_unit"] = (cash_cost, units.get("cash_cost_per_unit_reported", "unit"))
    stripping = current.get("stripping_ratio_reported")
    if stripping is not None:
        metrics["stripping_ratio"] = (stripping, units.get("stripping_ratio_reported", "ratio"))
    if reserves is not None:
        metrics["proven_probable_reserves"] = (reserves, reserve_unit or "unit")
    if production is not None:
        metrics["annual_production"] = (production, production_unit or "unit")
    return metrics
