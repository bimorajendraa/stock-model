"""Pure unit tests for Bank Indonesia SEKI parsing -- no network.

- Discovery parsing uses a real excerpt of the SEKI catalog page (fetched
  live 2026-07-26), including the real quirk that broke the first version
  of this parser: each PDF/XLS anchor has a **duplicate** ``href``
  attribute, and the data ``<td>`` cells for each row are not wrapped in
  their own ``<tr>`` at all -- both verified live before writing the
  parser, not assumed.
- The wide interest-rate-table extraction is tested against a small fake
  sheet object matching ``xlrd.Sheet``'s real interface
  (``nrows``/``ncols``/``cell_value``), built to reproduce the real
  file's actual quirk: year-block columns are NOT evenly spaced.
"""
from __future__ import annotations

import datetime as dt

from src.data_sources.macro.bi_seki import (
    SEKIDatasetDiscoveryAdapter,
    _extract_wide_row_series,
    _last_day_of_month,
)

# Real excerpt (2026-07-26) of https://www.bi.go.id/id/statistik/ekonomi-keuangan/seki/default.aspx --
# note the duplicate `href` attribute and the missing per-row <tr>.
_SEKI_CATALOG_HTML = """
<div class="page-table">
<table>
<tr><th colspan="4"><b>I. UANG DAN BANK</b></th></tr>
<td valign="top" align="left" width="30">I.1.</td>
<td valign="top" style='text-align:left;'>Uang Beredar dan Faktor-Faktor yang Mempengaruhinya</td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL1_1.pdf" href="#"><img src="/Style Library/biweb/img/icon-pdf.svg"></a></td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL1_1.xls" href="#"><img src="/Style Library/biweb/img/icon-excel.svg"></a></td>
<td valign="top" align="left" width="30">I.2.</td>
<td valign="top" style='text-align:left;'>Neraca Analitis Otoritas Moneter (Uang Primer)</td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL1_2.pdf" href="#"><img src="/Style Library/biweb/img/icon-pdf.svg"></a></td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL1_2.xls" href="#"><img src="/Style Library/biweb/img/icon-excel.svg"></a></td>
<tr><th colspan="4"><b>III. PASAR UANG DAN MODAL</b></th></tr>
<td valign="top" align="left" width="30">III.2.</td>
<td valign="top" style='text-align:left;'>Emisi Saham dan Obligasi pada Pasar Modal</td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL3_2.pdf" href="#"><img src="/Style Library/biweb/img/icon-pdf.svg"></a></td>
<td valign="top" align="center" width="20"><a href="https://www.bi.go.id/SEKI/tabel/TABEL3_2.xls" href="#"><img src="/Style Library/biweb/img/icon-excel.svg"></a></td>
</table>
</div>
"""


class _FakeClient:
    def __init__(self, text: str) -> None:
        self._text = text

    def get(self, url):
        class _Resp:
            status_code = 200
            text = self._text

        return _Resp()


def test_discover_parses_real_catalog_page_despite_duplicate_href_and_missing_tr():
    adapter = SEKIDatasetDiscoveryAdapter(client=_FakeClient(_SEKI_CATALOG_HTML))
    entries = adapter.discover()

    assert [e.table_id for e in entries] == ["I.1.", "I.2.", "III.2."]
    assert entries[0].section == "I. UANG DAN BANK"
    assert entries[2].section == "III. PASAR UANG DAN MODAL"
    assert entries[0].xls_url == "https://www.bi.go.id/SEKI/tabel/TABEL1_1.xls"
    assert entries[0].pdf_url == "https://www.bi.go.id/SEKI/tabel/TABEL1_1.pdf"
    assert entries[1].description == "Neraca Analitis Otoritas Moneter (Uang Primer)"


class _FakeSheet:
    """Minimal stand-in for xlrd.sheet.Sheet -- a dict of {(row, col): value}."""

    def __init__(self, cells: dict[tuple[int, int], object], nrows: int, ncols: int) -> None:
        self._cells = cells
        self.nrows = nrows
        self.ncols = ncols

    def cell_value(self, row: int, col: int):
        return self._cells.get((row, col), "")


def test_extract_wide_row_series_handles_unevenly_spaced_year_blocks():
    # Real quirk reproduced: 2017 starts at col 3 (4 real month columns
    # this time, not 12), 2018 starts at col 7 (uneven gap) -- the parser
    # must derive block width from the header row itself, never assume 12.
    cells = {
        (4, 3): 2017.0, (4, 7): 2018.0,
        (5, 3): "Jan", (5, 4): "Feb", (5, 5): "Mar", (5, 6): "Apr",
        (5, 7): "Jan", (5, 8): "Feb", (5, 9): "Mar",
        (6, 2): "Lending Facility dan Financing Facility",
        (6, 3): 5.5, (6, 4): 5.5, (6, 5): "-", (6, 6): 5.5,
        (6, 7): 6.0, (6, 8): 6.0, (6, 9): 6.0,
    }
    sheet = _FakeSheet(cells, nrows=7, ncols=10)

    points = _extract_wide_row_series(
        sheet, "Lending Facility dan Financing Facility", header_year_row=4, header_month_row=5, label_col=2
    )

    assert points == [
        (2017, 1, 5.5), (2017, 2, 5.5), (2017, 4, 5.5),  # March excluded -- "-" is not fabricated as 0
        (2018, 1, 6.0), (2018, 2, 6.0), (2018, 3, 6.0),
    ]


def test_extract_wide_row_series_handles_year_label_not_at_block_start():
    # Real bug found live (2026-07-26): the year *value* is not reliably
    # at its block's first column -- 2025's label sat at its block's
    # LAST populated column ("Dec"), not "Jan". A naive "year label marks
    # the block start" parser produced duplicate (year, month) keys
    # (every month appeared under both 2024 and 2025), which crashed the
    # real ON CONFLICT upsert with "cannot affect row a second time".
    # Reproduced here with the year label deliberately placed at the
    # block's *last* column instead of its first. label_col=10 is a
    # dedicated column, separate from the data columns 0-3.
    cells = {
        (4, 0): 2024.0,  # 2024's year label at its block's FIRST column (already worked before the fix)
        (5, 0): "Jan", (5, 1): "Feb",
        (6, 0): 5.5, (6, 1): 5.5,
        (5, 2): "Jan", (5, 3): "Feb",
        (4, 3): 2025.0,  # 2025's year label at its block's LAST column, not first -- the real quirk
        (6, 2): "-",  # Jan 2025 not yet published -- excluded, never fabricated
        (6, 3): 6.0,
        (6, 10): "Rate",  # the row's own label, in a dedicated column
    }
    sheet = _FakeSheet(cells, nrows=7, ncols=4)

    points = _extract_wide_row_series(sheet, "Rate", header_year_row=4, header_month_row=5, label_col=10)

    assert set(points) == {(2024, 1, 5.5), (2024, 2, 5.5), (2025, 2, 6.0)}
    # no duplicate (2024, 2)/(2025, 1) confusion, and Jan-2025's "-" never became a fabricated value


def test_extract_wide_row_series_returns_empty_when_label_not_found():
    sheet = _FakeSheet({(4, 0): 2017.0, (5, 0): "Jan"}, nrows=6, ncols=1)
    points = _extract_wide_row_series(sheet, "Not A Real Row", header_year_row=4, header_month_row=5, label_col=2)
    assert points == []


def test_last_day_of_month():
    assert _last_day_of_month(2026, 2) == dt.date(2026, 2, 28)
    assert _last_day_of_month(2024, 2) == dt.date(2024, 2, 29)  # leap year
    assert _last_day_of_month(2026, 6) == dt.date(2026, 6, 30)
