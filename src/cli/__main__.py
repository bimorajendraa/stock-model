"""Entry point for ``python -m src.cli``.

Examples:
    python -m src.cli providers check
    python -m src.cli companies import-aliases --file data/company_aliases.csv
    python -m src.cli market smoke-test --count 10
    python -m src.cli market backfill --count 50
    python -m src.cli market backfill --ticker BBCA
    python -m src.cli market update
    python -m src.cli corporate-actions sync --ticker BBCA
    python -m src.cli market reconcile --count 5
    python -m src.cli market build-clean --offset 0 --limit 150
    python -m src.cli features compute-technical --offset 0 --limit 150
    python -m src.cli fundamentals sync --tickers BBCA,TLKM
    python -m src.cli features compute-fundamental-ratios --tickers BBCA,TLKM
    python -m src.cli valuation compute --tickers BBCA,TLKM
    python -m src.cli recommendation compute --tickers BBCA,TLKM
    python -m src.cli macro sync
    python -m src.cli sector classify --offset 0 --limit 150
    python -m src.cli news sync
    python -m src.cli news compute-sentiment
    python -m src.cli sources audit
    python -m src.cli sources audit --category macro
    python -m src.cli sources report
    python -m src.cli features compute-technical --all --only-missing
    python -m src.cli fundamentals sync --sector Banks --only-missing
    python -m src.cli valuation compute --all --only-eligible --only-missing
    python -m src.cli recommendation compute --all --only-eligible --only-missing
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from src.cli.companies import cmd_companies_import_aliases
from src.cli.features import cmd_features_compute_fundamental_ratios, cmd_features_compute_technical
from src.cli.fundamentals import cmd_fundamentals_sync
from src.cli.macro import cmd_macro_sync
from src.cli.market import (
    cmd_corporate_actions_sync,
    cmd_market_backfill,
    cmd_market_build_clean,
    cmd_market_fetch_marketcap,
    cmd_market_reconcile,
    cmd_market_smoke_test,
    cmd_market_top_marketcap,
    cmd_market_update,
    cmd_providers_check,
)
from src.cli.news import cmd_news_compute_sentiment, cmd_news_sync
from src.cli.recommendation import cmd_recommendation_compute
from src.cli.sector import (
    cmd_sector_classify,
    cmd_sector_compute_disclosed_metrics,
    cmd_sector_compute_relative_metrics,
)
from src.cli.sources import cmd_sources_audit, cmd_sources_report
from src.cli.valuation import cmd_valuation_compute
from src.config.settings import get_settings
from src.database.session import make_engine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli")
    subparsers = parser.add_subparsers(dest="group", required=True)

    providers = subparsers.add_parser("providers", help="Provider capability commands")
    providers_sub = providers.add_subparsers(dest="action", required=True)
    providers_sub.add_parser("check", help="Probe provider capability and print the selection outcome")

    companies = subparsers.add_parser("companies", help="Company master-data commands")
    companies_sub = companies.add_subparsers(dest="action", required=True)
    aliases = companies_sub.add_parser(
        "import-aliases", help="Import validated ticker/name history from a CSV file"
    )
    aliases.add_argument("--file", required=True, help="CSV file with ticker and effective_from columns")

    market = subparsers.add_parser("market", help="Market data commands")
    market_sub = market.add_subparsers(dest="action", required=True)

    smoke = market_sub.add_parser("smoke-test", help="Real (no-fixture) ingestion smoke test")
    smoke.add_argument("--count", type=int, default=10)

    backfill = market_sub.add_parser("backfill", help="Full-history backfill")
    backfill.add_argument("--count", type=int, default=None)
    backfill.add_argument("--ticker", type=str, default=None)
    backfill.add_argument(
        "--offset", type=int, default=0, help="Ticker-ordered slice start, for chunking a full-universe run"
    )
    backfill.add_argument(
        "--limit", type=int, default=None, help="Ticker-ordered slice size, for chunking a full-universe run"
    )

    market_sub.add_parser("update", help="Incremental update for all companies")

    reconcile = market_sub.add_parser("reconcile", help="Cross-provider price reconciliation")
    reconcile.add_argument("--count", type=int, default=5)

    build_clean = market_sub.add_parser("build-clean", help="Preprocess raw prices into market_prices_clean")
    build_clean.add_argument("--offset", type=int, default=0)
    build_clean.add_argument("--limit", type=int, default=None)

    fetch_mcap = market_sub.add_parser(
        "fetch-marketcap", help="Fetch shares_outstanding via Yahoo Finance fast_info"
    )
    fetch_mcap.add_argument("--offset", type=int, default=0)
    fetch_mcap.add_argument("--limit", type=int, default=None)

    top_mcap = market_sub.add_parser(
        "top-marketcap", help="Print top N companies by market cap (DB-only, no network)"
    )
    top_mcap.add_argument("--count", type=int, default=50)

    sector = subparsers.add_parser("sector", help="Sector classification commands")
    sector_sub = sector.add_subparsers(dest="action", required=True)
    sector_classify = sector_sub.add_parser(
        "classify", help="Fetch real sector/industry classification via Yahoo Finance"
    )
    sector_classify.add_argument("--offset", type=int, default=0)
    sector_classify.add_argument("--limit", type=int, default=None)
    sector_classify.add_argument(
        "--tickers", type=str, default=None, help="Comma-separated ticker list, overrides --offset/--limit"
    )
    sector_classify.add_argument(
        "--all", dest="all_", action="store_true", help="Process every company, ignoring --offset/--limit"
    )
    sector_classify.add_argument(
        "--only-missing", action="store_true", help="Skip companies that already have a sector classification"
    )
    sector_classify.add_argument(
        "--resume",
        action="store_true",
        help="Alias for --only-missing -- continue an interrupted run",
    )
    sector_classify.add_argument(
        "--retry-deferred",
        action="store_true",
        help="With --only-missing, retry no-data/failed companies before their retry_after time",
    )
    sector_sub.add_parser(
        "compute-relative-metrics",
        help="Compute sector-relative percentile-rank metrics (DB-only, no network)",
    )
    sector_disclosed = sector_sub.add_parser(
        "compute-disclosed-metrics",
        help="Compute bank/mining metrics from disclosed filing facts",
    )
    sector_disclosed.add_argument("--offset", type=int, default=0)
    sector_disclosed.add_argument("--limit", type=int, default=None)
    sector_disclosed.add_argument("--tickers", type=str, default=None)
    sector_disclosed.add_argument("--all", dest="all_", action="store_true")

    ca = subparsers.add_parser("corporate-actions", help="Corporate action commands")
    ca_sub = ca.add_subparsers(dest="action", required=True)
    ca_sync = ca_sub.add_parser("sync", help="Sync corporate actions for one ticker")
    ca_sync.add_argument("--ticker", type=str, required=True)

    def _add_batch_args(p: argparse.ArgumentParser, *, eligible: bool = False) -> None:
        """Shared company-selection flags (spec: pipelines must accept
        --all/--sector/--resume/--only-missing, not just a hardcoded
        offset/limit slice -- see src/cli/batch.py)."""
        p.add_argument("--offset", type=int, default=0)
        p.add_argument("--limit", type=int, default=None)
        p.add_argument(
            "--tickers",
            type=str,
            default=None,
            help="Comma-separated ticker list, overrides --offset/--limit/--sector/--all",
        )
        p.add_argument(
            "--sector",
            type=str,
            default=None,
            help="Only companies in this sector (substring match on sector_name)",
        )
        p.add_argument(
            "--all",
            dest="all_",
            action="store_true",
            help="Process every eligible company, ignoring --offset/--limit",
        )
        p.add_argument(
            "--only-missing",
            action="store_true",
            help="Skip companies that already have output in this pipeline's target table",
        )
        p.add_argument(
            "--resume",
            action="store_true",
            help="Alias for --only-missing -- continue an interrupted run without redoing finished companies",
        )
        p.add_argument(
            "--retry-deferred",
            action="store_true",
            help="With --only-missing, retry no-data/failed companies before their retry_after time",
        )
        if eligible:
            p.add_argument(
                "--only-eligible",
                action="store_true",
                help="Skip companies missing this pipeline's real prerequisite data",
            )

    features = subparsers.add_parser("features", help="Feature engineering commands")
    features_sub = features.add_subparsers(dest="action", required=True)
    compute_technical = features_sub.add_parser(
        "compute-technical", help="Compute technical indicators into technical_features"
    )
    _add_batch_args(compute_technical)

    compute_ratios = features_sub.add_parser(
        "compute-fundamental-ratios", help="Compute fundamental ratios into financial_ratios"
    )
    _add_batch_args(compute_ratios, eligible=True)

    fundamentals = subparsers.add_parser("fundamentals", help="Fundamentals (financial statement) commands")
    fundamentals_sub = fundamentals.add_subparsers(dest="action", required=True)
    fundamentals_sync = fundamentals_sub.add_parser(
        "sync", help="Sync official IDX XBRL where configured, then research fallback"
    )
    _add_batch_args(fundamentals_sync)

    macro = subparsers.add_parser("macro", help="Macro/industry series commands")
    macro_sub = macro.add_subparsers(dest="action", required=True)
    macro_sync = macro_sub.add_parser(
        "sync", help="Sync macro/industry series via Yahoo Finance (research_only)"
    )
    macro_sync.add_argument(
        "--series", type=str, default=None, help="Comma-separated series_code list, default all known series"
    )

    valuation = subparsers.add_parser("valuation", help="Valuation commands")
    valuation_sub = valuation.add_subparsers(dest="action", required=True)
    valuation_compute = valuation_sub.add_parser(
        "compute", help="Compute historical/peer/optional-DCF valuation into valuation_results"
    )
    _add_batch_args(valuation_compute, eligible=True)

    recommendation = subparsers.add_parser("recommendation", help="Recommendation commands")
    recommendation_sub = recommendation.add_subparsers(dest="action", required=True)
    recommendation_compute = recommendation_sub.add_parser(
        "compute", help="Compute recommendation into recommendation_results"
    )
    _add_batch_args(recommendation_compute, eligible=True)

    news = subparsers.add_parser("news", help="News commands")
    news_sub = news.add_subparsers(dest="action", required=True)
    news_sync = news_sub.add_parser("sync", help="Sync recent articles from all real RSS feeds")
    news_sync.add_argument("--lookback-days", type=int, default=3)
    news_sentiment = news_sub.add_parser(
        "compute-sentiment", help="Score unscored (article, company) pairs into news_sentiment"
    )
    news_sentiment.add_argument("--limit", type=int, default=None)

    sources = subparsers.add_parser("sources", help="Data source capability/health registry commands")
    sources_sub = sources.add_subparsers(dest="action", required=True)
    sources_audit = sources_sub.add_parser(
        "audit", help="Probe every registered source and record real health status"
    )
    sources_audit.add_argument(
        "--category", type=str, default=None, help="Only audit sources in this data_category"
    )
    sources_sub.add_parser("report", help="Print the last recorded audit result for every registered source")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    engine = make_engine()
    with Session(engine) as session:
        if args.group == "providers" and args.action == "check":
            return cmd_providers_check(session, settings)
        if args.group == "companies" and args.action == "import-aliases":
            return cmd_companies_import_aliases(session, args.file)
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
        if args.group == "market" and args.action == "fetch-marketcap":
            return cmd_market_fetch_marketcap(session, settings, args.offset, args.limit)
        if args.group == "market" and args.action == "top-marketcap":
            return cmd_market_top_marketcap(session, args.count)
        if args.group == "sector" and args.action == "classify":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_sector_classify(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.all_,
                args.only_missing or args.resume,
                args.retry_deferred,
            )
        if args.group == "sector" and args.action == "compute-relative-metrics":
            return cmd_sector_compute_relative_metrics(session, settings)
        if args.group == "sector" and args.action == "compute-disclosed-metrics":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_sector_compute_disclosed_metrics(
                session, settings, args.offset, args.limit, tickers, args.all_
            )
        if args.group == "corporate-actions" and args.action == "sync":
            return cmd_corporate_actions_sync(session, settings, args.ticker)
        if args.group == "features" and args.action == "compute-technical":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_features_compute_technical(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.sector,
                args.all_,
                args.only_missing or args.resume,
                args.retry_deferred,
            )
        if args.group == "features" and args.action == "compute-fundamental-ratios":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_features_compute_fundamental_ratios(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.sector,
                args.all_,
                args.only_missing or args.resume,
                args.only_eligible,
                args.retry_deferred,
            )
        if args.group == "fundamentals" and args.action == "sync":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_fundamentals_sync(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.sector,
                args.all_,
                args.only_missing or args.resume,
                args.retry_deferred,
            )
        if args.group == "macro" and args.action == "sync":
            series = args.series.split(",") if args.series else None
            return cmd_macro_sync(session, settings, series)
        if args.group == "valuation" and args.action == "compute":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_valuation_compute(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.sector,
                args.all_,
                args.only_missing or args.resume,
                args.only_eligible,
                args.retry_deferred,
            )
        if args.group == "recommendation" and args.action == "compute":
            tickers = args.tickers.split(",") if args.tickers else None
            return cmd_recommendation_compute(
                session,
                settings,
                args.offset,
                args.limit,
                tickers,
                args.sector,
                args.all_,
                args.only_missing or args.resume,
                args.only_eligible,
                args.retry_deferred,
            )
        if args.group == "news" and args.action == "sync":
            return cmd_news_sync(session, settings, args.lookback_days)
        if args.group == "news" and args.action == "compute-sentiment":
            return cmd_news_compute_sentiment(session, settings, args.limit)
        if args.group == "sources" and args.action == "audit":
            return cmd_sources_audit(session, settings, args.category)
        if args.group == "sources" and args.action == "report":
            return cmd_sources_report(session, settings)

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
