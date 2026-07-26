"""Which macro/industry series this project actually has a verified real
source for -- provider-agnostic catalog (series_name, unit, and which DB
table each belongs to). Spec section 3.4: ``macro_series`` for
economy-wide series; the model's own docstring routes IHSG/commodity/
index series -- "market-wide series not tied to a single company" -- to
``industry_series`` instead.

Deliberately small: only series verified live against a real, working
source -- see ``yahoo_finance.py``'s docstring for the keyless FX/index/
commodity series, ``bps.py``'s docstring for the real Indonesia-specific
inflation/CPI series (needs a real, free, user-registered ``BPS_API_KEY``
-- see .env.example), and ``bi_rate.py``'s docstring for Bank Indonesia's
own real BI-Rate and JISDOR series -- both genuinely HTML-only (no JSON
API found live), but "no JSON API" is not the same as "not real data":
both pages are real, official, server-rendered HTML tables, parsed here
rather than treated as blocked.
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
    "bi_rate": SeriesDefinition("Bank Indonesia BI-Rate (BI 7-Day Reverse Repo Rate)", "percent", "macro"),
    "usdidr_jisdor": SeriesDefinition("USD/IDR JISDOR reference rate (Bank Indonesia)", "idr_per_usd", "macro"),
    "id_gdp_growth_annual": SeriesDefinition("Indonesia GDP growth, annual (World Bank, research fallback)", "percent_yoy", "macro"),
    "id_unemployment_rate_annual": SeriesDefinition("Indonesia unemployment rate, annual (World Bank, research fallback)", "percent", "macro"),
    "us_fed_funds_rate": SeriesDefinition("US Federal Funds Effective Rate (FRED, global rate-environment proxy)", "percent", "macro"),
    "us_dollar_index_broad": SeriesDefinition("US Dollar Index, Trade Weighted Broad (FRED, global rate-environment proxy)", "index_points", "macro"),
    "bi_lending_facility_rate": SeriesDefinition("Bank Indonesia Lending Facility rate (SEKI table I.25)", "percent", "macro"),
    "bi_deposit_facility_rate": SeriesDefinition("Bank Indonesia Deposit Facility rate (SEKI table I.25)", "percent", "macro"),
}
