"""CLI command implementations for the data source capability/health
registry (master-prompt "Section B")."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.market import _finish_pipeline_run, _start_pipeline_run
from src.config.settings import Settings
from src.data_sources.registry import run_audit, sync_catalog
from src.database.models.ops import DataSourceCapability


def cmd_sources_audit(session: Session, settings: Settings, category: str | None = None) -> int:
    run = _start_pipeline_run(session, "sources_audit")
    sync_catalog(session)
    session.commit()

    results = run_audit(session, settings, category=category)
    session.commit()

    healthy = sum(1 for _, status, _ in results if status.value == "healthy")
    for source_code, status, reason in results:
        line = f"{source_code}: {status.value}"
        if reason:
            line += f" ({reason})"
        print(line)

    _finish_pipeline_run(session, run, healthy, len(results) - healthy, None)
    print(f"\nSources-audit summary: {len(results)} probed, {healthy} healthy" + (f" (category={category})" if category else ""))
    return 0


def cmd_sources_report(session: Session, settings: Settings) -> int:
    rows = session.scalars(select(DataSourceCapability).order_by(DataSourceCapability.data_category, DataSourceCapability.source_code)).all()
    if not rows:
        print("No sources registered yet -- run `sources audit` first.")
        return 0

    print(f"{'source_code':<30} {'category':<14} {'type':<10} {'authority':<24} {'usage_mode':<20} {'health':<22} checked_at")
    for row in rows:
        checked = row.checked_at.isoformat(timespec="seconds") if row.checked_at else "never"
        print(
            f"{row.source_code:<30} {row.data_category:<14} {row.source_type.value:<10} "
            f"{row.authority_level.value:<24} {row.usage_mode.value:<20} {row.health_status.value:<22} {checked}"
        )
    return 0
