"""Market cap ranking, via Yahoo Finance's ``fast_info`` (verified live,
2026-07-25: real ``shares``/``marketCap`` fields for BBCA.JK).

Two-step, deliberately: (1) fetch ``shares_outstanding`` per company and
store it on ``companies`` -- a genuine data-quality improvement, that
field has been NULL since Tahap 1 because no adapter populated it; (2)
rank by market_cap = shares_outstanding * our own latest stored close
price (market_prices_clean), not Yahoo's own marketCap figure -- this
keeps the ranking internally consistent with data already verified in
this project rather than trusting a second, independently-timed price
snapshot from Yahoo.

Shares outstanding is a point-in-time snapshot applied going forward
only; it is NOT retroactively applied to historical market_prices_clean
rows (a real historical market cap needs the real historical share count,
which this doesn't have -- silently assuming constant shares across 10
years of history would be exactly the kind of quiet inaccuracy this
project avoids elsewhere).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.data_sources.market.yahoo_finance import default_yahoo_symbol
from src.database.models.company import Company
from src.database.models.market import MarketPriceClean


@dataclasses.dataclass
class MarketCapOutcome:
    ticker: str
    shares_outstanding: int | None = None
    skipped_reason: str | None = None


def fetch_and_store_shares_outstanding(session: Session, ticker: str) -> MarketCapOutcome:
    import yfinance as yf  # local import: keeps this optional dependency out of module-load path for callers that don't need it

    outcome = MarketCapOutcome(ticker=ticker)
    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    try:
        fast_info = yf.Ticker(default_yahoo_symbol(ticker)).fast_info
        shares = fast_info.get("shares")
    except Exception as exc:  # noqa: BLE001 -- yfinance raises assorted transport/parsing exceptions
        outcome.skipped_reason = f"fetch failed: {exc}"
        return outcome

    if not shares or shares <= 0:
        outcome.skipped_reason = "no shares data returned"
        return outcome

    company.shares_outstanding = int(shares)
    outcome.shares_outstanding = int(shares)
    return outcome


@dataclasses.dataclass
class RankedCompany:
    ticker: str
    company_name: str
    shares_outstanding: int
    latest_close: float
    market_cap: float
    price_date: dt.date


def rank_companies_by_market_cap(session: Session, top_n: int) -> list[RankedCompany]:
    """Pure DB read, no network -- ranks every company that has both a
    stored shares_outstanding and at least one market_prices_clean row,
    using each company's own most recent close."""
    companies = session.scalars(
        select(Company).where(Company.shares_outstanding.is_not(None))
    ).all()

    ranked: list[RankedCompany] = []
    for company in companies:
        latest = session.scalar(
            select(MarketPriceClean)
            .where(MarketPriceClean.company_id == company.id)
            .order_by(MarketPriceClean.trade_date.desc())
        )
        if latest is None or latest.close is None:
            continue
        close = float(latest.close)
        market_cap = close * company.shares_outstanding
        ranked.append(
            RankedCompany(
                ticker=company.ticker,
                company_name=company.company_name,
                shares_outstanding=company.shares_outstanding,
                latest_close=close,
                market_cap=market_cap,
                price_date=latest.trade_date,
            )
        )

    ranked.sort(key=lambda r: r.market_cap, reverse=True)
    return ranked[:top_n]
