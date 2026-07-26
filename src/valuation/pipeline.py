"""financial_ratios + financial_statement_items -> valuation_results
(spec section 8/10) via the self-relative method in ``relative.py``.

One valuation snapshot per (company, as_of_date) -- unlike
technical_features/financial_ratios (which represent "current knowledge,
fully recomputed each run"), valuation_results is meant to accumulate a
real history of point-in-time snapshots as this is run on different days,
so idempotency is scoped to *that day's* row only (re-running today
replaces today's row; it never touches a snapshot computed yesterday).
"""
from __future__ import annotations

import dataclasses
import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.database.models.company import Company
from src.database.models.fundamentals import FinancialRatio, FinancialStatementItem
from src.database.models.market import MarketPriceClean
from src.database.models.ml import ValuationResult
from src.valuation.relative import MIN_HISTORY_POINTS, combine_methods, percentile_fair_values

_PE_RATIO_NAMES = ("price_to_earnings__annual", "price_to_earnings__quarterly")
_PB_RATIO_NAMES = ("price_to_book__annual", "price_to_book__quarterly")
_BVPS_RATIO_NAMES = ("book_value_per_share__annual", "book_value_per_share__quarterly")
_EPS_ACCOUNT_CODES = ("eps_diluted", "eps_basic")


@dataclasses.dataclass
class ValuationOutcome:
    ticker: str
    as_of_date: dt.date | None = None
    methods_used: dict | None = None
    skipped_reason: str | None = None


def _ratio_history(session: Session, company_id: int, ratio_names: tuple[str, ...]) -> list[float]:
    rows = session.scalars(
        select(FinancialRatio.value).where(
            FinancialRatio.company_id == company_id,
            FinancialRatio.ratio_name.in_(ratio_names),
            FinancialRatio.is_applicable.is_(True),
        )
    ).all()
    return [float(v) for v in rows if v is not None]


def _latest_ratio_value(session: Session, company_id: int, ratio_names: tuple[str, ...]) -> float | None:
    row = session.execute(
        select(FinancialRatio.value)
        .where(
            FinancialRatio.company_id == company_id,
            FinancialRatio.ratio_name.in_(ratio_names),
            FinancialRatio.is_applicable.is_(True),
        )
        .order_by(FinancialRatio.available_at.desc())
    ).first()
    return float(row[0]) if row and row[0] is not None else None


def _latest_eps(session: Session, company_id: int) -> float | None:
    rows = session.execute(
        select(FinancialStatementItem.account_code, FinancialStatementItem.value, FinancialStatementItem.available_at).where(
            FinancialStatementItem.company_id == company_id,
            FinancialStatementItem.account_code.in_(_EPS_ACCOUNT_CODES),
        )
    ).all()
    usable = [r for r in rows if r.value is not None]
    if not usable:
        return None
    latest_available_at = max(r.available_at for r in usable)
    latest = {r.account_code: float(r.value) for r in usable if r.available_at == latest_available_at}
    # diluted preferred over basic when the same (most recent) statement reports both
    return latest.get("eps_diluted", latest.get("eps_basic"))


def _current_price(session: Session, company_id: int) -> tuple[float | None, dt.date | None]:
    row = session.execute(
        select(MarketPriceClean.close, MarketPriceClean.trade_date)
        .where(MarketPriceClean.company_id == company_id, MarketPriceClean.close.is_not(None))
        .order_by(MarketPriceClean.trade_date.desc())
    ).first()
    return (float(row[0]), row[1]) if row else (None, None)


def compute_valuation(session: Session, ticker: str, as_of_date: dt.date | None = None) -> ValuationOutcome:
    as_of_date = as_of_date or dt.datetime.now(dt.UTC).date()
    outcome = ValuationOutcome(ticker=ticker, as_of_date=as_of_date)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    pe_history = _ratio_history(session, company.id, _PE_RATIO_NAMES)
    pb_history = _ratio_history(session, company.id, _PB_RATIO_NAMES)
    latest_eps = _latest_eps(session, company.id)
    latest_bvps = _latest_ratio_value(session, company.id, _BVPS_RATIO_NAMES)
    current_price, current_price_date = _current_price(session, company.id)

    pe_result = percentile_fair_values(latest_eps, pe_history)
    pb_result = percentile_fair_values(latest_bvps, pb_history)
    combined = combine_methods({"relative_pe_historical": pe_result, "relative_pb_historical": pb_result})

    if not combined["methods_used"]:
        outcome.skipped_reason = (
            "insufficient historical multiple data for both P/E and P/B methods "
            f"(need >={MIN_HISTORY_POINTS} points each) -- run fundamentals sync + compute-fundamental-ratios first"
        )
        return outcome

    # min(1.0, ...) -- a simple 0-1 completeness heuristic (how much
    # historical multiple data fed this estimate relative to a modest
    # 8-point-per-method target), NOT a rigorous statistical confidence
    # score -- documented as such in docs/valuation.md, not oversold here.
    data_quality_score = min(1.0, (pe_result["n_points"] + pb_result["n_points"]) / 16)

    sensitivity = {
        "pe_method": pe_result,
        "pb_method": pb_result,
        "latest_eps": latest_eps,
        "latest_book_value_per_share": latest_bvps,
        "current_price": current_price,
        "current_price_date": current_price_date.isoformat() if current_price_date else None,
    }

    session.execute(
        delete(ValuationResult).where(ValuationResult.company_id == company.id, ValuationResult.as_of_date == as_of_date)
    )
    session.add(
        ValuationResult(
            company_id=company.id,
            as_of_date=as_of_date,
            methods_used=combined["methods_used"],
            fair_value_bear=combined["bear"],
            fair_value_base=combined["base"],
            fair_value_bull=combined["bull"],
            fair_value_conservative=combined["conservative"],
            sensitivity=sensitivity,
            data_quality_score=data_quality_score,
        )
    )
    outcome.methods_used = combined["methods_used"]
    return outcome
