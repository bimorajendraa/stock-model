"""Unit tests for company-name and alias entity matching."""
from __future__ import annotations

from src.database.models.company import Company, CompanyAlias
from src.ingestion.entity_matching import match_company_entities


def test_matches_current_company_name_without_ticker():
    company = Company(id=1, ticker="BBCA", company_name="PT Bank Central Asia Tbk")
    matches = match_company_entities("Laba Bank Central Asia tumbuh kuat", [company], [])
    assert len(matches) == 1
    assert matches[0].match_method == "company_name"
    assert matches[0].relevance_score == 0.90


def test_matches_previous_name_and_ticker_alias():
    company = Company(id=2, ticker="META", company_name="PT Nusantara Infrastructure Tbk")
    alias = CompanyAlias(
        company_id=2,
        previous_ticker="METAOLD",
        previous_name="PT Infrastruktur Nusantara Lama Tbk",
        effective_from=__import__("datetime").date(2020, 1, 1),
    )
    name_match = match_company_entities("Infrastruktur Nusantara Lama membayar utang", [company], [alias])
    ticker_match = match_company_entities("Saham METAOLD menguat", [company], [alias])
    assert name_match[0].match_method == "previous_name"
    assert ticker_match[0].match_method == "previous_ticker"


def test_provider_ticker_has_highest_relevance_and_short_generic_name_is_ignored():
    company = Company(id=3, ticker="EMAS", company_name="PT Emas Tbk")
    no_match = match_company_entities("Harga emas dunia naik", [company], [])
    explicit = match_company_entities("Harga emas dunia naik", [company], [], mentioned_tickers=["EMAS"])
    assert no_match == []
    assert explicit[0].match_method == "provider_ticker"
    assert explicit[0].relevance_score == 1.0
