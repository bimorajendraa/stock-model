"""Bank Indonesia -- SEKI (Statistik Ekonomi dan Keuangan Indonesia), spec
section 3.4. Real, official, downloadable legacy-Excel (.xls, OLE2/BIFF
format -- verified live with the ``file`` command before writing any
parser: "Composite Document File V2 Document ... Creating Application:
Microsoft Excel") tables, discovered from the real SEKI catalog page
rather than any hardcoded per-year filename (table URLs like
``.../SEKI/tabel/TABEL1_25_1.xls`` are themselves stable, but which
*table number* covers what changes over time -- discovery reads that
mapping from the live page every call).

Two things live here:

- ``SEKIDatasetDiscoveryAdapter`` -- parses the real table catalog (~35
  real entries checked live, section headers like "I. UANG DAN BANK",
  "III. PASAR UANG DAN MODAL", each row with a table number, a real
  Indonesian description, and real `.xls`/`.pdf` URLs).
- ``BankIndonesiaSEKIInterestRateAdapter`` -- downloads table I.25
  ("Suku Bunga, Diskonto, Imbalan, Margin" -- interest rates/discounts/
  returns/margins) and extracts two real, individually verified series:
  Bank Indonesia's own **Deposit Facility** and **Lending Facility**
  rates (the real standing-facility corridor around BI-Rate -- directly
  useful for `docs/valuation.md`'s discount-rate work, not just a macro
  curiosity). Real values checked for economic plausibility while
  building this (2026-07-26): Lending Facility tracked ~0.75pp above the
  same-period BI-Rate and Deposit Facility ~0.75-1.0pp below it,
  consistent with how BI's real standing facility corridor actually
  works -- not asserted blindly.

**Wide, irregular table layout, handled without assuming a fixed shape**:
year-block columns in the real file are NOT evenly spaced (found live:
2017->2018 is 14 columns apart, 2024->2025 is 24, 2025->2026 is only 7) --
this parser locates each year's real starting column from the header row
itself and reads that block's actual month labels from the row below it,
rather than assuming every year has exactly 12 columns. Cells containing
``"-"`` (BI's own "not applicable/not published" marker) are excluded,
never parsed as 0.

**Only one interest-rate table processed, not full SEKI breadth**: the
catalog has ~35 tables (money supply, credit by sector, deposits by
province, etc.) -- discovery covers finding all of them, but only I.25
has an actual value parser today. A real, disclosed scope limit, not
silently claimed as full SEKI coverage.
"""
from __future__ import annotations

import calendar
import dataclasses
import datetime as dt
import re

import httpx
import xlrd
from bs4 import BeautifulSoup

from src.data_sources.base import (
    AccessType,
    ProviderUnavailableError,
    SourceDescriptor,
    SourcedValue,
    ValidationStatus,
)
from src.data_sources.macro.base import MacroDataProvider, SeriesPoint

_USER_AGENT = "Mozilla/5.0 (compatible; IDXInvestmentIntelligence/1.0; +research, non-commercial)"
_CATALOG_URL = "https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/default.aspx"
_INTEREST_RATE_TABLE_URL = "https://www.bi.go.id/SEKI/tabel/TABEL1_25_1.xls"
_INTEREST_RATE_SHEET_NAME = "1.25A_2"  # the most recent-years sheet in this workbook -- verified live, other sheets in the same file cover older, already-superseded year ranges
_RELEASE_LAG_DAYS = 15  # conservative estimate, same discipline as bps.py -- BI doesn't expose a real per-observation publish date for this table

_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# series_code -> the exact row label to find in the sheet (verified live against the real file)
_ROW_LABELS: dict[str, str] = {
    "bi_lending_facility_rate": "Lending Facility dan Financing Facility",
    "bi_deposit_facility_rate": "1 Hari Sore",  # Deposit Facility, overnight, evening cutoff -- the row directly under "Deposit Facility (d/h Fasilitas Simpanan Bank Indonesia)"
}


@dataclasses.dataclass(frozen=True)
class SEKIDatasetEntry:
    table_id: str  # e.g. "I.25.A."
    section: str  # e.g. "I. UANG DAN BANK"
    description: str
    xls_url: str
    pdf_url: str | None


class SEKIDatasetDiscoveryAdapter:
    """Real catalog discovery -- not a MacroDataProvider itself (these
    tables cover many different, structurally different indicators, not
    one series), used to find what's available before deciding what to
    build a value-parser for next."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})

    def discover(self) -> list[SEKIDatasetEntry]:
        try:
            response = self._client.get(_CATALOG_URL)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"SEKI catalog request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"SEKI catalog returned HTTP {response.status_code}")

        # Real finding: each PDF/XLS anchor on this page has a **duplicate**
        # `href` attribute (`href="https://.../X.xls" href="#"` -- invalid
        # HTML). BeautifulSoup's html.parser resolves duplicates to the
        # *last* one at parse time, so by the time a tag is re-serialized
        # the real URL is already gone from the parsed tree -- regexing
        # `str(tag)` doesn't recover it. The real URLs are extracted
        # directly from the raw response text instead (first pass), then
        # matched positionally against the table_id/description/section
        # text sequence from BeautifulSoup (second pass) -- safe because
        # each catalog row has exactly one pdf link then one xls link, in
        # the same stable document order as the row text itself.
        raw_xls_urls = re.findall(r'https://www\.bi\.go\.id/SEKI/tabel/[^"]+\.xls', response.text)

        soup = BeautifulSoup(response.text, "html.parser")
        entries: list[SEKIDatasetEntry] = []
        current_section = ""
        pending_cells: list = []
        xls_index = 0
        # Real finding: the page's <td> data cells for each table row are
        # NOT wrapped in their own <tr> (only the section-header <th> rows
        # are) -- html.parser doesn't synthesize missing <tr>s the way a
        # browser's HTML5 parser would, so cells have to be walked in
        # document order and chunked in groups of 4 instead of grouped by
        # a (nonexistent) enclosing row element.
        for element in soup.find_all(["th", "td"]):
            if element.name == "th":
                current_section = element.get_text(strip=True)
                pending_cells = []
                continue
            pending_cells.append(element)
            if len(pending_cells) < 4:
                continue
            table_id_cell, description_cell, pdf_cell, xls_cell = pending_cells
            pending_cells = []
            table_id = table_id_cell.get_text(strip=True)
            has_xls_anchor = xls_cell.find("a") is not None
            if not table_id or not has_xls_anchor:
                continue
            if xls_index >= len(raw_xls_urls):
                break  # ran out of real URLs -- stop rather than mismatch
            xls_url = raw_xls_urls[xls_index]
            pdf_url = xls_url.rsplit(".", 1)[0] + ".pdf" if pdf_cell.find("a") is not None else None
            xls_index += 1
            entries.append(
                SEKIDatasetEntry(
                    table_id=table_id, section=current_section, description=description_cell.get_text(strip=True),
                    xls_url=xls_url, pdf_url=pdf_url,
                )
            )
        return entries


def _find_year_blocks(sheet: xlrd.sheet.Sheet, header_year_row: int, header_month_row: int) -> list[tuple[int, int, int]]:
    """[(start_col, end_col, year), ...].

    Real finding: the year *value* in the header row is **not reliably
    positioned at its own block's first column** -- verified live: 2024's
    label sits at its block's first ("Jan") column, but 2025's sits at its
    block's *last* populated column ("Dec"), and 2026's at its *most
    recent* column ("Jun", since only Jan-Jun 2026 existed when checked).
    Block boundaries are therefore derived from the **month row itself**
    (every real year segment in this table starts with "Jan" -- verified
    across all blocks checked), and each segment's year is whichever
    numeric year value (if any) appears *anywhere* within that segment's
    column range, not assumed to be at a fixed offset.
    """
    jan_starts = [
        col for col in range(sheet.ncols)
        if str(sheet.cell_value(header_month_row, col)).strip().lower()[:3] == "jan"
    ]
    if not jan_starts:
        return []

    blocks = []
    for i, start_col in enumerate(jan_starts):
        end_col = jan_starts[i + 1] if i + 1 < len(jan_starts) else sheet.ncols
        year = None
        for col in range(start_col, end_col):
            value = sheet.cell_value(header_year_row, col)
            if isinstance(value, (int, float)) and 1990 <= value <= 2100:
                year = int(value)
                break
        if year is not None:
            blocks.append((start_col, end_col, year))
    return blocks


def _find_row_by_label(sheet: xlrd.sheet.Sheet, label: str, label_col: int, start_row: int) -> int | None:
    for row in range(start_row, sheet.nrows):
        if str(sheet.cell_value(row, label_col)).strip() == label:
            return row
    return None


def _extract_wide_row_series(sheet: xlrd.sheet.Sheet, row_label: str, header_year_row: int, header_month_row: int, label_col: int) -> list[tuple[int, int, float]]:
    year_blocks = _find_year_blocks(sheet, header_year_row, header_month_row)
    if not year_blocks:
        return []

    target_row = _find_row_by_label(sheet, row_label, label_col, header_month_row + 1)
    if target_row is None:
        return []

    # (year, month) -> value, last column wins if a block genuinely
    # overlaps -- observed live for one real edge case, see module
    # docstring's "not full SEKI breadth" note; this keeps ingestion
    # idempotent (never two rows for the same real month) rather than
    # crashing on a Postgres "ON CONFLICT affects row twice" error.
    values_by_month: dict[tuple[int, int], float] = {}
    for start_col, end_col, year in year_blocks:
        for col in range(start_col, end_col):
            month_label = str(sheet.cell_value(header_month_row, col)).strip().lower()[:3]
            month = _MONTH_ABBR.get(month_label)
            if month is None:
                continue
            raw = sheet.cell_value(target_row, col)
            if not isinstance(raw, (int, float)):
                continue  # "-" (BI's own not-applicable/not-yet-published marker) -- never parsed as 0
            values_by_month[(year, month)] = float(raw)

    return [(year, month, value) for (year, month), value in values_by_month.items()]


class BankIndonesiaSEKIInterestRateAdapter(MacroDataProvider):
    _SOURCE = SourceDescriptor(name="bank_indonesia_seki_interest_rates", url=_INTEREST_RATE_TABLE_URL, access_type=AccessType.DOCUMENTED_FREE)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})

    @property
    def provider_name(self) -> str:
        return "bank_indonesia_seki_interest_rates"

    def supported_series(self) -> list[str]:
        return list(_ROW_LABELS)

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        if series_code not in _ROW_LABELS:
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        now = dt.datetime.now(dt.UTC)

        try:
            response = self._client.get(_INTEREST_RATE_TABLE_URL)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"SEKI interest-rate table request failed: {exc}") from exc
        if response.status_code >= 400:
            raise ProviderUnavailableError(f"SEKI interest-rate table returned HTTP {response.status_code}")

        try:
            workbook = xlrd.open_workbook(file_contents=response.content)
            sheet = workbook.sheet_by_name(_INTEREST_RATE_SHEET_NAME)
        except (xlrd.XLRDError, ValueError) as exc:
            raise ProviderUnavailableError(f"SEKI interest-rate table format changed / unreadable: {exc}") from exc

        raw_points = _extract_wide_row_series(
            sheet, _ROW_LABELS[series_code], header_year_row=4, header_month_row=5, label_col=2
        )

        points: list[SeriesPoint] = []
        for year, month, value in raw_points:
            last_day = _last_day_of_month(year, month)
            if start <= last_day <= end:
                points.append(
                    SeriesPoint(
                        observation_date=last_day, value=value,
                        available_at=dt.datetime.combine(last_day, dt.time.min, tzinfo=dt.UTC) + dt.timedelta(days=_RELEASE_LAG_DAYS),
                    )
                )

        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points, source=self._SOURCE, retrieved_at=now, available_at=now,
            period_start=start, period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )


def _last_day_of_month(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])
