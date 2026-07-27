"""High-precision company entity matching for untrusted news text."""
from __future__ import annotations

import dataclasses
import re
import unicodedata

from src.database.models.company import Company, CompanyAlias

_LEGAL_TOKENS = {
    "pt",
    "tbk",
    "persero",
    "perseroan",
    "terbatas",
    "limited",
    "indonesia",  # retained when needed, removed only as a legal/noise token
}


@dataclasses.dataclass(frozen=True, slots=True)
class EntityMatch:
    company_id: int
    relevance_score: float
    match_method: str
    matched_text: str


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).split())


def _name_variants(name: str) -> set[str]:
    normalized = _normalize(name)
    tokens = normalized.split()
    stripped = " ".join(token for token in tokens if token not in _LEGAL_TOKENS)
    variants = {normalized, stripped}
    # Precision guardrail: legal names reduced to a short/generic single
    # word are not safe entity evidence. Ticker matching still handles them.
    return {
        variant
        for variant in variants
        if len(variant) >= 8 and (len(variant.split()) >= 2 or len(variant) >= 12)
    }


def match_company_entities(
    text: str,
    companies: list[Company],
    aliases: list[CompanyAlias],
    mentioned_tickers: list[str] | None = None,
) -> list[EntityMatch]:
    """Match provider tickers, current/old tickers, names, and aliases."""
    normalized_text = f" {_normalize(text)} "
    explicit_tickers = {ticker.upper() for ticker in (mentioned_tickers or [])}
    aliases_by_company: dict[int, list[CompanyAlias]] = {}
    for alias in aliases:
        aliases_by_company.setdefault(alias.company_id, []).append(alias)

    matches: dict[int, EntityMatch] = {}

    def record(company_id: int, score: float, method: str, matched_text: str) -> None:
        existing = matches.get(company_id)
        if existing is None or score > existing.relevance_score:
            matches[company_id] = EntityMatch(company_id, score, method, matched_text[:256])

    for company in companies:
        ticker = company.ticker.upper()
        if ticker in explicit_tickers:
            record(company.id, 1.0, "provider_ticker", ticker)
        elif re.search(rf"\b{re.escape(ticker)}\b", text):
            record(company.id, 0.98, "ticker", ticker)

        for variant in _name_variants(company.company_name):
            if f" {variant} " in normalized_text:
                record(company.id, 0.90, "company_name", variant)

        for alias in aliases_by_company.get(company.id, []):
            if alias.previous_ticker:
                previous_ticker = alias.previous_ticker.upper()
                if previous_ticker in explicit_tickers or re.search(
                    rf"\b{re.escape(previous_ticker)}\b", text
                ):
                    record(company.id, 0.95, "previous_ticker", previous_ticker)
            if alias.previous_name:
                for variant in _name_variants(alias.previous_name):
                    if f" {variant} " in normalized_text:
                        record(company.id, 0.85, "previous_name", variant)
    return list(matches.values())
