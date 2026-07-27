"""Priority chain for official filings with a research fallback."""
from __future__ import annotations

import datetime as dt

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.fundamentals.base import FinancialStatementDocument, FundamentalsProvider

_CHAIN_SOURCE = SourceDescriptor(
    name="fundamentals_priority_chain",
    url="internal://data_sources/fundamentals/selector",
    access_type=AccessType.INTERNAL_DERIVED,
)


class PriorityFundamentalsProvider(FundamentalsProvider):
    """Prefer an official document per fiscal period, then fall back."""

    def __init__(self, primary: FundamentalsProvider, fallback: FundamentalsProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self._period_provider: dict[tuple[str, str], FundamentalsProvider] = {}

    @property
    def provider_name(self) -> str:
        return f"{self._primary.provider_name}_then_{self._fallback.provider_name}"

    def _list(self, provider: FundamentalsProvider, ticker: str, since: dt.date) -> list[str]:
        try:
            result = provider.list_available_statements(ticker, since)
        except ProviderUnavailableError:
            return []
        return result.value if result.is_usable() else []

    def list_available_statements(self, ticker: str, since: dt.date) -> SourcedValue[list[str]]:
        now = dt.datetime.now(dt.UTC)
        fallback_periods = self._list(self._fallback, ticker, since)
        primary_periods = self._list(self._primary, ticker, since)
        for period in fallback_periods:
            self._period_provider[(ticker.upper(), period)] = self._fallback
        for period in primary_periods:
            self._period_provider[(ticker.upper(), period)] = self._primary
        periods = sorted(set(fallback_periods) | set(primary_periods))
        return SourcedValue(
            value=periods,
            source=_CHAIN_SOURCE,
            retrieved_at=now,
            available_at=now,
            period_start=since,
            period_end=None,
            validation_status=ValidationStatus.VALID if periods else ValidationStatus.INSUFFICIENT,
        )

    def get_statement(self, ticker: str, fiscal_period: str) -> SourcedValue[FinancialStatementDocument]:
        provider = self._period_provider.get((ticker.upper(), fiscal_period))
        if provider is not None:
            return provider.get_statement(ticker, fiscal_period)

        primary = self._primary.get_statement(ticker, fiscal_period)
        if primary.is_usable():
            return primary
        return self._fallback.get_statement(ticker, fiscal_period)
