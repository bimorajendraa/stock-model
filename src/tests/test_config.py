"""Settings should load with safe defaults and respect env var overrides."""
from src.config.settings import Settings


def test_settings_default_timezone_is_jakarta():
    settings = Settings(_env_file=None)
    assert settings.timezone == "Asia/Jakarta"


def test_settings_llm_provider_defaults_to_none():
    settings = Settings(_env_file=None)
    assert settings.llm_provider == "none"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings(_env_file=None)
    assert settings.app_env == "production"
