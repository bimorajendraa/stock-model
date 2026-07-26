"""Which macro/industry series this project actually has a verified real
source for -- provider-agnostic catalog (series_name, unit, and which DB
table each belongs to). Spec section 3.4: ``macro_series`` for
economy-wide series; the model's own docstring routes IHSG/commodity/
index series -- "market-wide series not tied to a single company" -- to
``industry_series`` instead.

Deliberately small: only series verified live against a real, working
source -- see ``yahoo_finance.py``'s docstring for the keyless FX/index/
commodity series, and ``bps.py``'s docstring for the real Indonesia-
specific inflation/CPI series (needs a real, free, user-registered
``BPS_API_KEY`` -- see .env.example). Bank Indonesia's own BI-Rate page
is still HTML-only, no API found live -- not covered by any adapter here.
"""
from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class SeriesDefinition:
    series_name: str
    unit_of_measure: str
    table: str  # "macro" | "industry"


SERIES_CATALOG: dict[str, SeriesDefinition] = {
    "usdidr_fx": SeriesDefinition("USD/IDR spot exchange rate", "idr_per_usd", "macro"),
    "us_10y_treasury_yield": SeriesDefinition(
        "US 10-Year Treasury yield (global rate-environment proxy, NOT BI-Rate)", "percent", "macro"
    ),
    "ihsg_composite": SeriesDefinition("IDX Composite Index (IHSG)", "index_points", "industry"),
    "wti_crude_oil": SeriesDefinition("WTI Crude Oil futures", "usd_per_barrel", "industry"),
    "id_inflation_mom": SeriesDefinition("Indonesia inflation, month-over-month (BPS, national)", "percent_mom", "macro"),
}
