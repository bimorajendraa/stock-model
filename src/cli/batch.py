"""Shared company-selection and safe-batch-execution helpers for CLI
pipeline commands that process many companies (sector/technical/
fundamentals/valuation/recommendation) -- "Section L" of the master data-coverage
task: pipelines must accept ``--all``/``--sector``/``--resume``/
``--only-missing`` (not just a hardcoded top-50/offset-limit slice), use
real per-company batching (one commit per company, never one transaction
for the full equity universe), and record a per-company failure without failing the whole
batch.

``--resume`` is intentionally an alias for ``--only-missing`` here, not a
separate checkpoint mechanism: given this codebase's existing idempotent-
per-company-commit design, "skip whatever already has a row" is already
a correct, self-healing way to continue an interrupted run, regardless of
exactly where it stopped -- a separate saved-cursor mechanism would add
real complexity without a real correctness gain over that.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from typing import TypeAlias, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from src.database.models.company import AssetType, Company, SectorRegistry
from src.database.models.ops import PipelineCompanyResult

_ResultT = TypeVar("_ResultT")
_CompanyIdSelect: TypeAlias = Select[tuple[int]]

NO_DATA_RETRY_DELAY = dt.timedelta(days=7)
FAILURE_RETRY_DELAY = dt.timedelta(hours=1)
_TRANSIENT_SKIP_PREFIXES = ("provider unavailable:", "fetch failed:")


def select_companies(
    session: Session,
    *,
    tickers: list[str] | None = None,
    sector: str | None = None,
    offset: int = 0,
    limit: int | None = None,
    all_: bool = False,
    active_only: bool = True,
    asset_type: str | None = AssetType.EQUITY.value,
    only_missing_stmt: _CompanyIdSelect | None = None,
    only_eligible_stmt: _CompanyIdSelect | None = None,
    defer_attempts_for_pipeline: str | None = None,
) -> list[Company]:
    """Ticker list (if given) wins outright -- bypasses sector/active/
    only_missing/only_eligible/offset/limit entirely (an explicit ticker
    list is always exactly what it says). Otherwise: filter by sector/
    active/equity status, then by only_eligible/only_missing (real finding: this
    order matters -- filtering *before* the offset/limit slice, not after,
    is what makes ``--limit 15 --only-missing`` actually return up to 15
    companies that need work, instead of only whatever's left after
    slicing the raw company list first and then discovering most of that
    slice already had data), and only *then* apply --all or the
    offset/limit slice."""
    if tickers:
        return [c for c in (session.scalar(select(Company).where(Company.ticker == t)) for t in tickers) if c]

    stmt = select(Company)
    if sector:
        stmt = stmt.join(SectorRegistry, Company.sector_registry_id == SectorRegistry.id).where(
            SectorRegistry.sector_name.ilike(f"%{sector}%")
        )
    if active_only:
        stmt = stmt.where(Company.status == "active")
    if asset_type is not None:
        stmt = stmt.where(Company.asset_type == asset_type)
    stmt = stmt.order_by(Company.ticker)

    companies = list(session.scalars(stmt))
    if only_eligible_stmt is not None:
        companies = filter_has_prerequisite(session, companies, only_eligible_stmt)
    if only_missing_stmt is not None:
        companies = filter_only_missing(session, companies, only_missing_stmt)
    if defer_attempts_for_pipeline is not None:
        companies = filter_deferred_attempts(session, companies, defer_attempts_for_pipeline)

    if all_:
        return companies
    return companies[offset : offset + limit] if limit is not None else companies[offset:]


def filter_only_missing(
    session: Session,
    companies: list[Company],
    already_has_stmt: _CompanyIdSelect,
) -> list[Company]:
    """``already_has_stmt``: a ``select(SomeModel.company_id).distinct()``
    statement (or any statement yielding company_id scalars) identifying
    companies that already have at least one row in the pipeline's own
    target table -- one bulk query, not one existence check per company."""
    existing_ids = set(session.scalars(already_has_stmt))
    return [c for c in companies if c.id not in existing_ids]


def filter_has_prerequisite(
    session: Session,
    companies: list[Company],
    has_prerequisite_stmt: _CompanyIdSelect,
) -> list[Company]:
    """The ``--only-eligible`` counterpart to ``filter_only_missing``:
    ``has_prerequisite_stmt`` identifies companies that already have the
    *upstream* data a pipeline needs (e.g. valuation needs
    financial_ratios; recommendation needs valuation_results) -- keeps
    only those, so a large batch doesn't spend time/output on companies
    the underlying pipeline would immediately skip anyway."""
    eligible_ids = set(session.scalars(has_prerequisite_stmt))
    return [c for c in companies if c.id in eligible_ids]


def filter_deferred_attempts(
    session: Session,
    companies: list[Company],
    pipeline_name: str,
    *,
    as_of: dt.datetime | None = None,
) -> list[Company]:
    """Exclude companies whose latest attempt is still in cooldown.

    Only the latest attempt per pipeline/company controls selection. This
    matters when an operator force-retries a previously empty ticker: the
    newer result must replace the older cooldown decision.
    """
    if not companies:
        return []

    latest_ids = (
        select(func.max(PipelineCompanyResult.id).label("id"))
        .where(PipelineCompanyResult.pipeline_name == pipeline_name)
        .group_by(PipelineCompanyResult.company_id)
        .subquery()
    )
    now = as_of or dt.datetime.now(dt.UTC)
    deferred_ids = set(
        session.scalars(
            select(PipelineCompanyResult.company_id)
            .join(latest_ids, PipelineCompanyResult.id == latest_ids.c.id)
            .where(
                PipelineCompanyResult.retry_after.is_not(None),
                PipelineCompanyResult.retry_after > now,
            )
        )
    )
    return [company for company in companies if company.id not in deferred_ids]


@dataclasses.dataclass
class BatchRunner:
    """Tracks per-company results across a large batch, and executes each
    company's work isolated from the others -- a single company's real
    exception (network error, malformed provider response, etc.) is
    caught, rolled back, and recorded, never allowed to abort the rest of
    a 900+-company run."""

    pipeline_name: str | None = None
    pipeline_run_id: int | None = None
    no_data_retry_delay: dt.timedelta = NO_DATA_RETRY_DELAY
    failure_retry_delay: dt.timedelta = FAILURE_RETRY_DELAY
    written: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = dataclasses.field(default_factory=list)

    def run(
        self,
        session: Session,
        ticker: str,
        fn: Callable[..., _ResultT],
        *args: object,
        company_id: int | None = None,
        **kwargs: object,
    ) -> _ResultT | None:
        attempted_at = dt.datetime.now(dt.UTC)
        try:
            # A savepoint rolls back only this company's writes. A full
            # session.rollback() would also erase the still-pending
            # PipelineRun when the first company in a batch fails.
            with session.begin_nested():
                result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 -- deliberate: one company's failure must never crash the batch
            self.failed += 1
            message = f"{type(exc).__name__}: {exc}"
            self.failures.append((ticker, message))
            self._record_result(
                session,
                company_id,
                "failed",
                attempted_at,
                attempted_at + self.failure_retry_delay,
                message,
            )
            print(f"{ticker}: FAILED ({type(exc).__name__}: {exc})")
            return None

        skipped_reason = getattr(result, "skipped_reason", None)
        if skipped_reason:
            status = (
                "failed" if str(skipped_reason).lower().startswith(_TRANSIENT_SKIP_PREFIXES) else "no_data"
            )
            retry_delay = self.failure_retry_delay if status == "failed" else self.no_data_retry_delay
            self._record_result(
                session,
                company_id,
                status,
                attempted_at,
                attempted_at + retry_delay,
                str(skipped_reason),
            )
        else:
            self._record_result(session, company_id, "succeeded", attempted_at, None, None)
        return result

    def _record_result(
        self,
        session: Session,
        company_id: int | None,
        status: str,
        attempted_at: dt.datetime,
        retry_after: dt.datetime | None,
        message: str | None,
    ) -> None:
        """Append an attempt result when this runner has run context."""
        if self.pipeline_name is None or self.pipeline_run_id is None or company_id is None:
            return
        session.add(
            PipelineCompanyResult(
                pipeline_run_id=self.pipeline_run_id,
                company_id=company_id,
                pipeline_name=self.pipeline_name,
                status=status,
                attempted_at=attempted_at,
                retry_after=retry_after,
                message=message,
            )
        )

    def failure_summary(self, limit: int = 20) -> str | None:
        """Compact failure detail suitable for ``pipeline_runs``.

        Console output still reports every failure as it happens. The DB
        summary is bounded so a provider-wide outage cannot create an
        unreasonably large ``error_message`` value for a 900+ company run.
        """
        if not self.failures:
            return None

        shown = self.failures[:limit]
        lines = [f"{ticker}: {message}" for ticker, message in shown]
        omitted = len(self.failures) - len(shown)
        if omitted:
            lines.append(f"... {omitted} additional failure(s) omitted")
        return "\n".join(lines)
