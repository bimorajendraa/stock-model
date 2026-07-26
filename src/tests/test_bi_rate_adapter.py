"""Pure unit tests for Bank Indonesia BI-Rate/JISDOR HTML parsing -- no
network. Fixture HTML snippets below are excerpts of the *real* page
structure fetched live from bi.go.id on 2026-07-26 (verified with a bare
curl first, before any parsing code was written -- see
``src/data_sources/macro/bi_rate.py``'s module docstring), not invented
markup.
"""
from __future__ import annotations

import datetime as dt

from bs4 import BeautifulSoup

from src.data_sources.macro.bi_rate import (
    _end_of_day,
    _find_postback_target,
    _parse_bi_rate_rows,
    _parse_indonesian_date,
    _parse_jisdor_rows,
)

_BI_RATE_HTML = """
<div class="page-table table-responsive page-table--bordered mb-3" id="tableData">
    <table class="table table-striped table-no-bordered table-lg">
        <thead>
            <tr class="table-header">
                <th scope="col" class="text-center">No</th>
                <th scope="col" class="text-center">Tanggal</th>
                <th scope="col" class="text-center">BI-Rate</th>
                <th scope="col" class="text-center">Pranala Siaran Pers</th>
            </tr>
        </thead>
        <tbody>
            <tr>
                <th scope="row" class="text-center">1</th>
                <td class="text-center">22 Juli 2026</td>
                <td class="text-center">5.75 %</td>
                <td class="text-center"><a href="/id/publikasi/ruang-media/news-release/Pages/sp_2814226.aspx">Lihat</a></td>
            </tr>
            <tr>
                <th scope="row" class="text-center">2</th>
                <td class="text-center">18 Juni 2026</td>
                <td class="text-center">5.75 %</td>
                <td class="text-center"><a href="/id/publikasi/ruang-media/news-release/Pages/sp_2812626.aspx">Lihat</a></td>
            </tr>
            <tr>
                <th scope="row" class="text-center">3</th>
                <td class="text-center">9 Juni 2026</td>
                <td class="text-center">5.50 %</td>
                <td class="text-center"><a href="/id/publikasi/ruang-media/news-release/Pages/sp_2811926.aspx">Lihat</a></td>
            </tr>
        </tbody>
    </table>
</div>
"""

_JISDOR_HTML = """
<div class="page-table table-responsive page-table--bordered mb-3" id="tableData">
    <table class="table table-striped table-no-bordered table-lg">
        <thead>
            <tr class="table-header">
                <th scope="col" class="text-center">Tanggal</th>
                <th scope="col" class="text-center">Kurs</th>
            </tr>
        </thead>
        <tbody>
            <tr><td class="text-center">24 Juli 2026</td><td class="text-center">Rp17.973,00</td></tr>
            <tr><td class="text-center">23 Juli 2026</td><td class="text-center">Rp17.915,00</td></tr>
            <tr><td class="text-center">22 Juli 2026</td><td class="text-center">Rp17.909,00</td></tr>
        </tbody>
    </table>
</div>
"""

_PAGINATION_HTML = """
<span class="pagination">
<input type="image" disabled="disabled" class="aspNetDisabled prev" />
<span class="page-link--custom active">1</span>
<a class="pagination-list" href="javascript:__doPostBack('ctl00$ctl54$g_78f62327$ctl00$DataPagerBI7DRR$ctl01$ctl01','')">2</a>
<a class="pagination-list" href="javascript:__doPostBack('ctl00$ctl54$g_78f62327$ctl00$DataPagerBI7DRR$ctl01$ctl02','')">3</a>
<a href="javascript:__doPostBack('ctl00$ctl54$g_78f62327$ctl00$DataPagerBI7DRR$ctl01$ctl05','')">...</a>
</span>
"""


def test_parse_indonesian_date():
    assert _parse_indonesian_date("22 Juli 2026") == dt.date(2026, 7, 22)
    assert _parse_indonesian_date("9 Juni 2026") == dt.date(2026, 6, 9)
    assert _parse_indonesian_date("1 Januari 2020") == dt.date(2020, 1, 1)


def test_parse_bi_rate_rows_from_real_page_structure():
    soup = BeautifulSoup(_BI_RATE_HTML, "html.parser")
    rows = _parse_bi_rate_rows(soup)
    assert rows == [
        {"observation_date": dt.date(2026, 7, 22), "value": 5.75},
        {"observation_date": dt.date(2026, 6, 18), "value": 5.75},
        {"observation_date": dt.date(2026, 6, 9), "value": 5.50},
    ]


def test_parse_jisdor_rows_from_real_page_structure_handles_indonesian_number_format():
    soup = BeautifulSoup(_JISDOR_HTML, "html.parser")
    rows = _parse_jisdor_rows(soup)
    assert rows == [
        {"observation_date": dt.date(2026, 7, 24), "value": 17973.00},
        {"observation_date": dt.date(2026, 7, 23), "value": 17915.00},
        {"observation_date": dt.date(2026, 7, 22), "value": 17909.00},
    ]


def test_find_postback_target_locates_control_by_visible_page_number():
    soup = BeautifulSoup(_PAGINATION_HTML, "html.parser")
    assert _find_postback_target(soup, 2) == "ctl00$ctl54$g_78f62327$ctl00$DataPagerBI7DRR$ctl01$ctl01"
    assert _find_postback_target(soup, 3) == "ctl00$ctl54$g_78f62327$ctl00$DataPagerBI7DRR$ctl01$ctl02"


def test_find_postback_target_returns_none_when_page_not_visible():
    soup = BeautifulSoup(_PAGINATION_HTML, "html.parser")
    assert _find_postback_target(soup, 99) is None


def test_end_of_day_never_earlier_than_the_observation_date():
    result = _end_of_day(dt.date(2026, 7, 22))
    assert result.date() == dt.date(2026, 7, 22)
    assert result.tzinfo is not None
