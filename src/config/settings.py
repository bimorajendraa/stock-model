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
    llm_provider: str = Field(default="none", alias="LLM_PROVIDER")  # "anthropic" | "ollama" | "none"
    llm_api_base: str | None = Field(default=None, alias="LLM_API_BASE")
    llm_api_key: str | None = Field(default=None, alias="LLM_API_KEY")
    llm_model: str | None = Field(default=None, alias="LLM_MODEL")

    # --- Data provider credentials (all optional; adapters degrade gracefully) ---
    news_provider_api_key: str | None = Field(default=None, alias="NEWS_PROVIDER_API_KEY")
    market_data_provider_api_key: str | None = Field(default=None, alias="MARKET_DATA_PROVIDER_API_KEY")

    # --- Cache ---
    redis_url: str | None = Field(default=None, alias="REDIS_URL")


@lru_cache
def get_settings() -> Settings:
    return Settings()
