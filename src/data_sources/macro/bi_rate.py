"""Bank Indonesia -- BI-Rate and JISDOR, both real, official, server-
rendered HTML tables (spec section 3.4). Neither exposes a JSON API, but
per this task's own rule: "tidak adanya API JSON bukan alasan untuk
menyatakan data terblokir" -- checked live (2026-07-26), both pages are
genuine static-rendered HTML (verified with a bare ``curl``, no
JavaScript execution needed) and `robots.txt` allows both paths
(`Disallow` only lists `/_layouts`, `/Style Library`, a handful of other
unrelated paths -- not these).

- **BI-Rate** (`/id/statistik/indikator/bi-rate.aspx`): table columns No/
  Tanggal/BI-Rate/Pranala Siaran Pers. Indonesian date format ("22 Juli
  2026"), rate as "5.75 %". `available_at` is the decision date itself
  (BI announces its RDG rate decision the same day, always in the
  afternoon per real central-bank practice) -- estimated as that date's
  end-of-day, never earlier than the real announcement.
- **JISDOR** (`/id/statistik/informasi-kurs/jisdor/default.aspx`): table
  columns Tanggal/Kurs. Same date format, rate as Indonesian-formatted
  currency ("Rp17.973,00" -- dot=thousands, comma=decimal). JISDOR is
  published same-day (BI's real publication practice: the day's rate is
  set and published each business morning) -- `available_at` uses the
  observation date itself, end-of-day estimate.

**Pagination is real ASP.NET WebForms postback** (`__doPostBack`,
`__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION` hidden fields),
not a simple `?page=N` query string -- verified live by inspecting the
raw HTML's pagination links before writing any parsing code. Followed
here exactly as a real browser clicking "2", "3", ... would (not a
bypass of anything -- the page's own robots.txt already allows this
path). **Depth capped at ``_MAX_PAGES`` (default 5)** -- a real, disclosed
limitation, not silently presented as full history: BI-Rate's ~monthly
cadence means 5 pages already covers several years, but JISDOR is daily,
so 5 pages is only ~2 months of real trading days. Chasing the "..."
ellipsis for deeper history was deliberately left for a later increment
rather than adding more postback-chain complexity now.
"""
from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable

import httpx
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
_MAX_PAGES = 5  # see module docstring -- a real, disclosed depth cap, not full history

_INDONESIAN_MONTHS = {
    "januari": 1, "februari": 2, "maret": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "agustus": 8, "september": 9, "oktober": 10, "november": 11, "desember": 12,
}


def _parse_indonesian_date(text: str) -> dt.date:
    day_str, month_str, year_str = text.strip().split()
    month = _INDONESIAN_MONTHS[month_str.lower()]
    return dt.date(int(year_str), month, int(day_str))


def _end_of_day(observation_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(observation_date, dt.time(hour=16, minute=0), tzinfo=dt.UTC)


def _extract_hidden(soup: BeautifulSoup, field_id: str) -> str:
    tag = soup.find(id=field_id)
    return tag["value"] if tag and tag.has_attr("value") else ""


def _find_postback_target(soup: BeautifulSoup, page_number: int) -> str | None:
    """Find the ``__doPostBack('CONTROL_NAME', '')`` target for the
    pagination link whose visible text is ``page_number`` -- located by
    link text, not a hardcoded control-name pattern, since the control's
    GUID-laden prefix is generated per-page-instance."""
    for anchor in soup.find_all("a", href=True):
        if anchor.get_text(strip=True) == str(page_number):
            match = re.search(r"__doPostBack\('([^']+)'\s*,\s*'[^']*'\)", anchor["href"])
            if match:
                return match.group(1)
    return None


def _fetch_paginated_rows(
    client: httpx.Client, url: str, row_parser: Callable[[BeautifulSoup], list[dict]], max_pages: int = _MAX_PAGES
) -> list[dict]:
    response = client.get(url)
    if response.status_code >= 400:
        raise ProviderUnavailableError(f"GET {url} returned HTTP {response.status_code}")
    soup = BeautifulSoup(response.text, "html.parser")
    all_rows = list(row_parser(soup))

    page_number = 1
    while page_number < max_pages:
        target = _find_postback_target(soup, page_number + 1)
        if target is None:
            break  # no further page visible in the current pagination window
        form_data = {
            "__EVENTTARGET": target,
            "__EVENTARGUMENT": "",
            "__VIEWSTATE": _extract_hidden(soup, "__VIEWSTATE"),
            "__VIEWSTATEGENERATOR": _extract_hidden(soup, "__VIEWSTATEGENERATOR"),
            "__EVENTVALIDATION": _extract_hidden(soup, "__EVENTVALIDATION"),
        }
        response = client.post(url, data=form_data)
        if response.status_code >= 400:
            break
        soup = BeautifulSoup(response.text, "html.parser")
        new_rows = row_parser(soup)
        if not new_rows:
            break
        all_rows.extend(new_rows)
        page_number += 1

    return all_rows


def _parse_bi_rate_rows(soup: BeautifulSoup) -> list[dict]:
    table = soup.find(id="tableData")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        date_text, rate_text = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
        try:
            observation_date = _parse_indonesian_date(date_text)
            value = float(rate_text.replace("%", "").strip().replace(",", "."))
        except (ValueError, KeyError):
            continue
        rows.append({"observation_date": observation_date, "value": value})
    return rows


def _parse_jisdor_rows(soup: BeautifulSoup) -> list[dict]:
    table = soup.find(id="tableData")
    if table is None:
        return []
    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        date_text, rate_text = cells[0].get_text(strip=True), cells[1].get_text(strip=True)
        try:
            observation_date = _parse_indonesian_date(date_text)
            # Indonesian number format: "Rp17.973,00" -> dot=thousands, comma=decimal
            cleaned = rate_text.replace("Rp", "").strip().replace(".", "").replace(",", ".")
            value = float(cleaned)
        except (ValueError, KeyError):
            continue
        rows.append({"observation_date": observation_date, "value": value})
    return rows


class BankIndonesiaRateHTMLAdapter(MacroDataProvider):
    """BI-Rate (BI 7-Day Reverse Repo Rate), spec section 3.4."""

    _URL = "https://www.bi.go.id/id/statistik/indikator/bi-rate.aspx"
    _SOURCE = SourceDescriptor(name="bank_indonesia_bi_rate_html", url=_URL, access_type=AccessType.DOCUMENTED_FREE)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})

    @property
    def provider_name(self) -> str:
        return "bank_indonesia_bi_rate_html"

    def supported_series(self) -> list[str]:
        return ["bi_rate"]

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        if series_code != "bi_rate":
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        now = dt.datetime.now(dt.UTC)
        try:
            raw_rows = _fetch_paginated_rows(self._client, self._URL, _parse_bi_rate_rows)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"bank_indonesia_bi_rate_html request failed: {exc}") from exc

        points = [
            SeriesPoint(observation_date=row["observation_date"], value=row["value"], available_at=_end_of_day(row["observation_date"]))
            for row in raw_rows
            if start <= row["observation_date"] <= end
        ]
        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points, source=self._SOURCE, retrieved_at=now, available_at=now,
            period_start=start, period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )


class BankIndonesiaJISDORAdapter(MacroDataProvider):
    """JISDOR (Jakarta Interbank Spot Dollar Rate) USD/IDR reference rate, spec section 3.4."""

    _URL = "https://www.bi.go.id/id/statistik/informasi-kurs/jisdor/default.aspx"
    _SOURCE = SourceDescriptor(name="bank_indonesia_jisdor_html", url=_URL, access_type=AccessType.DOCUMENTED_FREE)

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": _USER_AGENT})

    @property
    def provider_name(self) -> str:
        return "bank_indonesia_jisdor_html"

    def supported_series(self) -> list[str]:
        return ["usdidr_jisdor"]

    def get_series(self, series_code: str, start: dt.date, end: dt.date) -> SourcedValue[list[SeriesPoint]]:
        if series_code != "usdidr_jisdor":
            raise ValueError(f"unsupported series_code: {series_code!r} -- see supported_series()")
        now = dt.datetime.now(dt.UTC)
        try:
            raw_rows = _fetch_paginated_rows(self._client, self._URL, _parse_jisdor_rows)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(f"bank_indonesia_jisdor_html request failed: {exc}") from exc

        points = [
            SeriesPoint(observation_date=row["observation_date"], value=row["value"], available_at=_end_of_day(row["observation_date"]))
            for row in raw_rows
            if start <= row["observation_date"] <= end
        ]
        points.sort(key=lambda p: p.observation_date)
        return SourcedValue(
            value=points, source=self._SOURCE, retrieved_at=now, available_at=now,
            period_start=start, period_end=end,
            validation_status=ValidationStatus.VALID if points else ValidationStatus.INSUFFICIENT,
        )
