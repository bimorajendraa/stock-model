"""Central application configuration.

All configuration flows through environment variables (see .env.example).
No secrets are hard-coded here. This module must stay provider-agnostic --
it knows *that* a database and providers are configured, never business logic.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Jakarta", alias="APP_TIMEZONE")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://idx:idx@localhost:5432/idx_intelligence",
        alias="DATABASE_URL",
    )

    # --- Orchestration (Prefect) ---
    prefect_api_url: str | None = Field(default=None, alias="PREFECT_API_URL")

    # --- Experiment tracking ---
    mlflow_tracking_uri: str | None = Field(default=None, alias="MLFLOW_TRACKING_URI")

    # --- LLM (narrative/explanation only -- never numeric computation) ---
    llm_provider: str = Field(default="none", alias="LLM_PROVIDER")  # "anthropic" | "openrouter" | "ollama" | "none"
    llm_api_base: str | None = Field(default=None, alias="LLM_API_BASE")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")

    # --- Data provider credentials (all optional; adapters degrade gracefully) ---
    news_provider_api_key: str | None = Field(default=None, alias="NEWS_PROVIDER_API_KEY")
    market_data_provider_api_key: str | None = Field(default=None, alias="MARKET_DATA_PROVIDER_API_KEY")
    twelve_data_api_key: str | None = Field(default=None, alias="TWELVE_DATA_API_KEY")
    sectors_app_api_key: str | None = Field(default=None, alias="SECTORS_APP_API_KEY")
    bps_api_key: str | None = Field(default=None, alias="BPS_API_KEY")
    fred_api_key: str | None = Field(default=None, alias="FRED_API_KEY")

    # --- Market data provider selection (spec: multi-provider capability system) ---
    market_data_provider: str = Field(default="auto", alias="MARKET_DATA_PROVIDER")  # "auto" | "twelve_data" | "yahoo_finance"
    market_data_usage_mode: str = Field(default="research", alias="MARKET_DATA_USAGE_MODE")  # "research" | "production"
    enable_yahoo_finance_fallback: bool = Field(default=True, alias="ENABLE_YAHOO_FINANCE_FALLBACK")
    verify_latest_price_with_idx: bool = Field(default=True, alias="VERIFY_LATEST_PRICE_WITH_IDX")
    price_adjustment_policy: str = Field(default="provider_split_adjusted", alias="PRICE_ADJUSTMENT_POLICY")
    # "raw" | "provider_split_adjusted" | "provider_all_adjusted" | "internally_verified_adjusted"

    # --- Rate limiting / retry (OHLCV ingestion) ---
    ohlcv_batch_size: int = Field(default=20, alias="OHLCV_BATCH_SIZE")
    ohlcv_max_retries: int = Field(default=4, alias="OHLCV_MAX_RETRIES")
    ohlcv_request_timeout_seconds: int = Field(default=30, alias="OHLCV_REQUEST_TIMEOUT_SECONDS")
    ohlcv_request_delay_seconds: float = Field(default=2.0, alias="OHLCV_REQUEST_DELAY_SECONDS")

    # --- Cache ---
    redis_url: str | None = Field(default=None, alias="REDIS_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
