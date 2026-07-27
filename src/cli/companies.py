"""CLI commands for company master-data maintenance."""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.ingestion.company_aliases import import_company_aliases


def cmd_companies_import_aliases(session: Session, csv_path: str) -> int:
    run = _start_pipeline_run(session, "companies_import_aliases")
    try:
        outcome = import_company_aliases(session, csv_path)
    except ValueError as exc:
        session.rollback()
        run = _start_pipeline_run(session, "companies_import_aliases")
        _finish_pipeline_run(session, run, 0, 1, str(exc))
        print(f"FAILED: {exc}")
        return 1

    _finish_pipeline_run(session, run, outcome.rows_seen, 0, None)
    print(
        f"Company-alias import: {outcome.rows_seen} rows, "
        f"{outcome.created} created, {outcome.updated} updated"
    )
    return 0
