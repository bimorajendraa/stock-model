"""Entry point for ``python -m src.cli``.

Examples:
    python -m src.cli providers check
    python -m src.cli market smoke-test --count 10
    python -m src.cli market backfill --count 50
    python -m src.cli market backfill --ticker BBCA
    python -m src.cli market update
    python -m src.cli corporate-actions sync --ticker BBCA
    python -m src.cli market reconcile --count 5
    python -m src.cli market build-clean --offset 0 --limit 150
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from src.cli.market import (
    cmd_corporate_actions_sync,
    cmd_market_backfill,
    cmd_market_build_clean,
    cmd_market_reconcile,
    cmd_market_smoke_test,
    cmd_market_update,
    cmd_providers_check,
)
from src.config.settings import get_settings
from src.database.session import make_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="group", required=True)

    providers = subparsers.add_parser("providers", help="Provider capability commands")
    providers_sub = providers.add_subparsers(dest="action", required=True)
    providers_sub.add_parser("check", help="Probe provider capability and print the selection outcome")

    market = subparsers.add_parser("market", help="Market data commands")
    market_sub = market.add_subparsers(dest="action", required=True)

    smoke = market_sub.add_parser("smoke-test", help="Real (no-fixture) ingestion smoke test")
    smoke.add_argument("--count", type=int, default=10)

    backfill = market_sub.add_parser("backfill", help="Full-history backfill")
    backfill.add_argument("--count", type=int, default=None)
    backfill.add_argument("--ticker", type=str, default=None)
    backfill.add_argument("--offset", type=int, default=0, help="Ticker-ordered slice start, for chunking a full-universe run")
    backfill.add_argument("--limit", type=int, default=None, help="Ticker-ordered slice size, for chunking a full-universe run")

    market_sub.add_parser("update", help="Incremental update for all companies")

    reconcile = market_sub.add_parser("reconcile", help="Cross-provider price reconciliation")
    reconcile.add_argument("--count", type=int, default=5)

    build_clean = market_sub.add_parser("build-clean", help="Preprocess raw prices into market_prices_clean")
    build_clean.add_argument("--offset", type=int, default=0)
    build_clean.add_argument("--limit", type=int, default=None)

    ca = subparsers.add_parser("corporate-actions", help="Corporate action commands")
    ca_sub = ca.add_subparsers(dest="action", required=True)
    ca_sync = ca_sub.add_parser("sync", help="Sync corporate actions for one ticker")
    ca_sync.add_argument("--ticker", type=str, required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine()
    with Session(engine) as session:
        if args.group == "providers" and args.action == "check":
            return cmd_providers_check(session, settings)
        if args.group == "market" and args.action == "smoke-test":
            return cmd_market_smoke_test(session, settings, args.count)
        if args.group == "market" and args.action == "backfill":
            return cmd_market_backfill(session, settings, args.count, args.ticker, args.offset, args.limit)
        if args.group == "market" and args.action == "update":
            return cmd_market_update(session, settings)
        if args.group == "market" and args.action == "reconcile":
            return cmd_market_reconcile(session, settings, args.count)
        if args.group == "market" and args.action == "build-clean":
            return cmd_market_build_clean(session, settings, args.offset, args.limit)
        if args.group == "corporate-actions" and args.action == "sync":
            return cmd_corporate_actions_sync(session, settings, args.ticker)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
