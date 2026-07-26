"""Deterministic fundamental ratio computation (spec section 8) -- pure
functions, no DB/network. An LLM must never compute a ratio directly
(spec section 2.15); this module is the actual, auditable arithmetic that
does.

Every ratio is either a real number or ``None``. ``None`` means "not
computable from what this statement reports" (a missing input, or a
zero/negative denominator that would make the ratio meaningless) -- never
a fabricated ``0`` (spec section 2.12/6.3, and ``FinancialRatio.
is_applicable``'s own docstring: "False => not_applicable, not zero").
Callers should treat every ``None`` here as ``is_applicable=False``, not
drop the row -- the fact that a bank has no computable ``current_ratio``
is itself real, useful information (it's a sector-structure fact, not a
data gap to paper over).
"""
from __future__ import annotations

RATIO_NAMES = (
    "gross_margin",
    "operating_margin",
    "net_margin",
    "roe",
    "roa",
    "debt_to_equity",
    "debt_to_assets",
    "current_ratio",
    "fcf_margin",
    "ocf_margin",
    "book_value_per_share",
    "price_to_earnings",
    "price_to_book",
)


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def compute_statement_ratios(items: dict[str, float]) -> dict[str, float | None]:
    """Ratios computable purely from a statement's own line items (no
    market price needed)."""
    revenue = items.get("revenue")
    return {
        "gross_margin": safe_div(items.get("gross_profit"), revenue),
        "operating_margin": safe_div(items.get("operating_income"), revenue),
        "net_margin": safe_div(items.get("net_income"), revenue),
        "roe": safe_div(items.get("net_income"), items.get("total_equity")),
        "roa": safe_div(items.get("net_income"), items.get("total_assets")),
        "debt_to_equity": safe_div(items.get("total_debt"), items.get("total_equity")),
        "debt_to_assets": safe_div(items.get("total_debt"), items.get("total_assets")),
        "current_ratio": safe_div(items.get("current_assets"), items.get("current_liabilities")),
        "fcf_margin": safe_div(items.get("free_cash_flow"), revenue),
        "ocf_margin": safe_div(items.get("operating_cash_flow"), revenue),
        "book_value_per_share": safe_div(items.get("total_equity"), items.get("shares_outstanding")),
    }


def compute_price_dependent_ratios(items: dict[str, float], price: float | None) -> dict[str, float | None]:
    """P/E and P/B need a market price -- caller is responsible for
    supplying a point-in-time-correct one (the close on/before the
    statement's ``available_at``, never a later price)."""
    book_value_per_share = safe_div(items.get("total_equity"), items.get("shares_outstanding"))
    eps = items.get("eps_diluted")
    if eps is None:
        eps = items.get("eps_basic")
    # Negative/zero EPS makes P/E conventionally undefined (not just a
    # negative number) -- standard financial-data-provider convention,
    # reported as N/A rather than a mechanically-computed negative ratio.
    price_to_earnings = safe_div(price, eps) if eps is not None and eps > 0 else None
    return {
        "price_to_earnings": price_to_earnings,
        "price_to_book": safe_div(price, book_value_per_share),
    }


def compute_all_ratios(items: dict[str, float], price: float | None) -> dict[str, float | None]:
    ratios = compute_statement_ratios(items)
    ratios.update(compute_price_dependent_ratios(items, price))
    return ratios
