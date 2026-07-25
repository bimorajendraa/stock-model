"""Shared provenance envelope for every value pulled from an external source.

Every adapter method returns records wrapped in ``SourcedValue`` (or a
subclass) rather than bare numbers/dicts -- this is the enforcement point
for spec §2.11: "Setiap angka harus menyimpan nama sumber, URL, waktu
pengambilan, periode data, waktu tersedia untuk publik, dan status
validasi." A value without this envelope cannot be written to any fact
table, because every fact table requires SourceLineageMixin columns that
come from these fields.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import enum
from typing import Generic, TypeVar

T = TypeVar("T")


class AccessType(str, enum.Enum):
    OFFICIAL = "official"
    DOCUMENTED_FREE = "documented_free"
    FALLBACK_PROVIDER = "fallback_provider"
    # For rows this platform derives itself (e.g. market_prices_clean from
    # market_prices_raw) -- not an external source at all, and deliberately
    # NOT "official": that word is reserved elsewhere in this codebase for
    # IDX/government sources specifically, and reusing it here would blur
    # a distinction the rest of the docs/code are careful about.
    INTERNAL_DERIVED = "internal_derived"


class ValidationStatus(str, enum.Enum):
    PENDING = "pending"
    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"
    INSUFFICIENT = "data_tidak_mencukupi"


@dataclasses.dataclass(frozen=True, slots=True)
class SourceDescriptor:
    """Identifies *which* provider produced a value -- must correspond to a
    row in the ``data_source_registry`` table."""

    name: str
    url: str
    access_type: AccessType


@dataclasses.dataclass(frozen=True, slots=True)
class SourcedValue(Generic[T]):
    """One value plus its full provenance envelope."""

    value: T | None
    source: SourceDescriptor
    retrieved_at: dt.datetime
    available_at: dt.datetime
    period_start: dt.date | None
    period_end: dt.date | None
    validation_status: ValidationStatus = ValidationStatus.PENDING

    def is_usable(self) -> bool:
        return self.value is not None and self.validation_status in (
            ValidationStatus.VALID,
            ValidationStatus.SUSPECT,
        )


class ProviderUnavailableError(RuntimeError):
    """Raised by an adapter when a source cannot be reached or denies access.

    Callers (ingestion jobs) must catch this and fall back to the next
    configured provider (spec §33 degraded mode) -- never substitute
    fabricated data.
    """


class TermsOfServiceViolation(RuntimeError):
    """Raised if an adapter would have to violate robots.txt, ToS, auth
    bypass, or a paywall to fetch data (spec §2.5-6). This is a hard stop,
    not something a caller retries or falls back from silently -- it must
    surface as a configuration/integration error.
    """
