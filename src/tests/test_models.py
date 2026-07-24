"""Model-layer sanity checks: metadata builds, lineage mixin is applied
where required, and the spec's minimum table list (§4) is present.

No database connection required -- these only exercise SQLAlchemy's mapper
configuration, not an actual Postgres instance (that's covered by the
integration-marked tests / manual `alembic upgrade head` verification).
"""
from sqlalchemy.orm import configure_mappers

from src.database import models  # noqa: F401 -- populates Base.metadata
from src.database.base import Base

REQUIRED_TABLES = {
    "companies",
    "company_aliases",
    "sector_registry",
    "market_prices_raw",
    "market_prices_clean",
    "corporate_actions",
    "financial_statements_raw",
    "financial_statement_items",
    "financial_ratios",
    "sector_specific_metrics",
    "dividends",
    "macro_series",
    "industry_series",
    "news_articles",
    "news_entities",
    "news_sentiment",
    "reputation_events",
    "technical_features",
    "fundamental_features",
    "model_features",
    "predictions",
    "valuation_results",
    "recommendation_results",
    "model_versions",
    "training_runs",
    "data_quality_results",
    "data_source_registry",
    "pipeline_runs",
    "alerts",
}

FACT_TABLES_REQUIRING_LINEAGE = {
    "market_prices_raw",
    "market_prices_clean",
    "corporate_actions",
    "dividends",
    "financial_statements_raw",
    "financial_statement_items",
    "financial_ratios",
    "sector_specific_metrics",
    "macro_series",
    "industry_series",
    "news_articles",
    "reputation_events",
}

LINEAGE_COLUMNS = {
    "source_id",
    "retrieved_at",
    "available_at",
    "period_start",
    "period_end",
    "currency",
    "unit",
    "is_restated",
    "quality_status",
    "raw_payload_hash",
}


def test_mappers_configure_without_error():
    configure_mappers()


def test_all_spec_tables_present():
    actual_tables = set(Base.metadata.tables.keys())
    missing = REQUIRED_TABLES - actual_tables
    assert not missing, f"Missing tables from spec §4 minimum list: {missing}"


def test_fact_tables_carry_lineage_columns():
    for table_name in FACT_TABLES_REQUIRING_LINEAGE:
        table = Base.metadata.tables[table_name]
        column_names = set(table.columns.keys())
        missing = LINEAGE_COLUMNS - column_names
        assert not missing, f"{table_name} is missing lineage columns: {missing}"


def test_source_id_fk_points_at_data_source_registry():
    table = Base.metadata.tables["market_prices_raw"]
    fk_targets = {fk.target_fullname for fk in table.columns["source_id"].foreign_keys}
    assert "data_source_registry.id" in fk_targets
