"""Point-in-time historical, peer-relative, and optional DCF valuation.

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
from src.database.models.fundamentals import FinancialRatio, FinancialStatementItem, FinancialStatementRaw
from src.database.models.market import MarketPriceClean
from src.database.models.ml import ValuationResult
from src.valuation.dcf import DCFInputs, discounted_cash_flow
from src.valuation.peer import peer_multiple_fair_values
from src.valuation.relative import MIN_HISTORY_POINTS, combine_methods, percentile_fair_values

_PE_RATIO_NAMES = ("price_to_earnings__annual", "price_to_earnings__quarterly")
_PB_RATIO_NAMES = ("price_to_book__annual", "price_to_book__quarterly")
_BVPS_RATIO_NAMES = ("book_value_per_share__annual", "book_value_per_share__quarterly")
_EPS_ACCOUNT_CODES = ("eps_diluted", "eps_basic")


@dataclasses.dataclass(frozen=True, slots=True)
class ValuationAssumptions:
    discount_rate: float | None = None
    near_term_growth_rate: float | None = None
    terminal_growth_rate: float | None = None
    projection_years: int = 5

    def is_complete(self) -> bool:
        return None not in (self.discount_rate, self.near_term_growth_rate, self.terminal_growth_rate)


@dataclasses.dataclass
class ValuationOutcome:
    ticker: str
    as_of_date: dt.date | None = None
    methods_used: dict | None = None
    skipped_reason: str | None = None


def _cutoff(as_of_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(as_of_date, dt.time.max, tzinfo=dt.UTC)


def _ratio_history(
    session: Session,
    company_id: int,
    ratio_names: tuple[str, ...],
    as_of_date: dt.date,
) -> list[float]:
    rows = session.scalars(
        select(FinancialRatio.value).where(
            FinancialRatio.company_id == company_id,
            FinancialRatio.ratio_name.in_(ratio_names),
            FinancialRatio.is_applicable.is_(True),
            FinancialRatio.available_at <= _cutoff(as_of_date),
        )
    ).all()
    return [float(v) for v in rows if v is not None]


def _latest_ratio_value(
    session: Session,
    company_id: int,
    ratio_names: tuple[str, ...],
    as_of_date: dt.date,
) -> float | None:
    row = session.execute(
        select(FinancialRatio.value)
        .where(
            FinancialRatio.company_id == company_id,
            FinancialRatio.ratio_name.in_(ratio_names),
            FinancialRatio.is_applicable.is_(True),
            FinancialRatio.available_at <= _cutoff(as_of_date),
        )
        .order_by(FinancialRatio.available_at.desc())
    ).first()
    return float(row[0]) if row and row[0] is not None else None


def _latest_item_value(
    session: Session,
    company_id: int,
    account_codes: tuple[str, ...],
    as_of_date: dt.date,
    statement_type: str | None = None,
) -> float | None:
    statement = (
        select(
            FinancialStatementItem.account_code,
            FinancialStatementItem.value,
            FinancialStatementItem.available_at,
        )
        .join(FinancialStatementRaw, FinancialStatementRaw.id == FinancialStatementItem.statement_id)
        .where(
            FinancialStatementItem.company_id == company_id,
            FinancialStatementItem.account_code.in_(account_codes),
            FinancialStatementItem.available_at <= _cutoff(as_of_date),
        )
    )
    if statement_type is not None:
        statement = statement.where(FinancialStatementRaw.statement_type == statement_type)
    rows = session.execute(statement).all()
    usable = [r for r in rows if r.value is not None]
    if not usable:
        return None
    latest_available_at = max(r.available_at for r in usable)
    latest = {r.account_code: float(r.value) for r in usable if r.available_at == latest_available_at}
    return next((latest[code] for code in account_codes if code in latest), None)


def _latest_annual_dcf_snapshot(
    session: Session,
    company_id: int,
    as_of_date: dt.date,
) -> tuple[dict[str, float], dt.datetime | None]:
    """Return DCF inputs from one annual statement, never mixed periods."""
    statement_row = session.execute(
        select(FinancialStatementRaw.id, FinancialStatementRaw.available_at)
        .join(FinancialStatementItem, FinancialStatementItem.statement_id == FinancialStatementRaw.id)
        .where(
            FinancialStatementRaw.company_id == company_id,
            FinancialStatementRaw.statement_type == "annual",
            FinancialStatementRaw.available_at <= _cutoff(as_of_date),
            FinancialStatementItem.account_code == "free_cash_flow",
            FinancialStatementItem.value > 0,
            FinancialStatementItem.available_at <= _cutoff(as_of_date),
        )
        .order_by(FinancialStatementRaw.available_at.desc())
    ).first()
    if statement_row is None:
        return {}, None

    rows = session.execute(
        select(FinancialStatementItem.account_code, FinancialStatementItem.value).where(
            FinancialStatementItem.statement_id == statement_row.id,
            FinancialStatementItem.account_code.in_(
                (
                    "free_cash_flow",
                    "cash_and_equivalents",
                    "total_debt",
                    "shares_outstanding",
                    "shares_diluted",
                    "shares_basic",
                )
            ),
        )
    ).all()
    values = {code: float(value) for code, value in rows if value is not None}
    return values, statement_row.available_at


def _current_price(
    session: Session,
    company_id: int,
    as_of_date: dt.date,
) -> tuple[float | None, dt.date | None]:
    row = session.execute(
        select(MarketPriceClean.close, MarketPriceClean.trade_date)
        .where(
            MarketPriceClean.company_id == company_id,
            MarketPriceClean.close.is_not(None),
            MarketPriceClean.trade_date <= as_of_date,
        )
        .order_by(MarketPriceClean.trade_date.desc())
    ).first()
    return (float(row[0]), row[1]) if row else (None, None)


def _peer_multiples(
    session: Session,
    company: Company,
    ratio_names: tuple[str, ...],
    as_of_date: dt.date,
) -> list[float]:
    if company.sector_registry_id is None:
        return []
    peer_ids = list(
        session.scalars(
            select(Company.id).where(
                Company.sector_registry_id == company.sector_registry_id,
                Company.id != company.id,
                Company.asset_type == "equity",
                Company.status == "active",
            )
        )
    )
    values = [
        _latest_ratio_value(session, peer_id, ratio_names, as_of_date)
        for peer_id in peer_ids
    ]
    return [value for value in values if value is not None and value > 0]


def compute_valuation(
    session: Session,
    ticker: str,
    as_of_date: dt.date | None = None,
    assumptions: ValuationAssumptions | None = None,
) -> ValuationOutcome:
    as_of_date = as_of_date or dt.datetime.now(dt.UTC).date()
    outcome = ValuationOutcome(ticker=ticker, as_of_date=as_of_date)

    company = session.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        outcome.skipped_reason = "no matching Company row"
        return outcome

    assumptions = assumptions or ValuationAssumptions()
    pe_history = _ratio_history(session, company.id, _PE_RATIO_NAMES, as_of_date)
    pb_history = _ratio_history(session, company.id, _PB_RATIO_NAMES, as_of_date)
    latest_eps = _latest_item_value(session, company.id, _EPS_ACCOUNT_CODES, as_of_date)
    latest_bvps = _latest_ratio_value(session, company.id, _BVPS_RATIO_NAMES, as_of_date)
    current_price, current_price_date = _current_price(session, company.id, as_of_date)

    pe_result = percentile_fair_values(latest_eps, pe_history)
    pb_result = percentile_fair_values(latest_bvps, pb_history)
    peer_pe_result = peer_multiple_fair_values(
        latest_eps,
        _peer_multiples(session, company, _PE_RATIO_NAMES, as_of_date),
    )
    peer_pb_result = peer_multiple_fair_values(
        latest_bvps,
        _peer_multiples(session, company, _PB_RATIO_NAMES, as_of_date),
    )

    dcf_result = {
        "bear": None,
        "base": None,
        "bull": None,
        "conservative": None,
        "grid": {},
        "skipped_reason": "DCF assumptions are not fully configured",
    }
    if assumptions.is_complete():
        dcf_snapshot, dcf_available_at = _latest_annual_dcf_snapshot(
            session, company.id, as_of_date
        )
        shares = next(
            (
                dcf_snapshot[code]
                for code in ("shares_outstanding", "shares_diluted", "shares_basic")
                if code in dcf_snapshot
            ),
            None,
        )
        required_inputs = {
            "free_cash_flow": dcf_snapshot.get("free_cash_flow"),
            "cash_and_equivalents": dcf_snapshot.get("cash_and_equivalents"),
            "total_debt": dcf_snapshot.get("total_debt"),
            "shares_outstanding": shares,
        }
        if all(value is not None for value in required_inputs.values()):
            dcf_result = discounted_cash_flow(
                DCFInputs(
                    base_free_cash_flow=float(required_inputs["free_cash_flow"]),
                    cash=float(required_inputs["cash_and_equivalents"]),
                    debt=float(required_inputs["total_debt"]),
                    shares_outstanding=float(required_inputs["shares_outstanding"]),
                    discount_rate=float(assumptions.discount_rate),
                    near_term_growth_rate=float(assumptions.near_term_growth_rate),
                    terminal_growth_rate=float(assumptions.terminal_growth_rate),
                    projection_years=assumptions.projection_years,
                )
            )
            if dcf_result["base"] is None:
                dcf_result["skipped_reason"] = "DCF rate/growth assumptions are invalid"
            dcf_result["statement_available_at"] = dcf_available_at.isoformat()
        else:
            missing_inputs = [name for name, value in required_inputs.items() if value is None]
            dcf_result["skipped_reason"] = (
                "latest positive-FCF annual statement is missing: " + ", ".join(missing_inputs)
            )

    estimates = {
        "relative_pe_historical": pe_result,
        "relative_pb_historical": pb_result,
        "relative_pe_sector": peer_pe_result,
        "relative_pb_sector": peer_pb_result,
        "discounted_cash_flow": dcf_result,
    }
    combined = combine_methods(estimates)

    if not combined["methods_used"]:
        outcome.skipped_reason = (
            "insufficient data for historical, sector-relative, and configured DCF methods "
            f"(historical methods need >={MIN_HISTORY_POINTS} points)"
        )
        return outcome

    # min(1.0, ...) -- a simple 0-1 completeness heuristic (how much
    # historical multiple data fed this estimate relative to a modest
    # 8-point-per-method target), NOT a rigorous statistical confidence
    # score -- documented as such in docs/valuation.md, not oversold here.
    history_score = min(1.0, (pe_result["n_points"] + pb_result["n_points"]) / 16)
    method_score = len(combined["methods_used"]) / len(estimates)
    data_quality_score = (history_score + method_score) / 2

    sensitivity = {
        "pe_method": pe_result,
        "pb_method": pb_result,
        "peer_pe_method": peer_pe_result,
        "peer_pb_method": peer_pb_result,
        "dcf_method": dcf_result,
        "dcf_configured": assumptions.is_complete(),
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
