# Authorized IDX XBRL archive

The official-filing adapter intentionally reads local XBRL files plus a JSON
manifest. IDX's public filing page currently returns HTTP 403 to automated
clients, so this project does not scrape it or bypass its access controls.
Obtain the files through an authorized/manual IDX workflow and preserve their
official document references.

## Manifest

Place the manifest and XBRL instances under one directory. `xbrl_file` must
remain inside that directory; path traversal is rejected.

```json
{
  "account_map": {
    "IssuerSpecificGrossLoans": "gross_loans"
  },
  "filings": [
    {
      "ticker": "BBCA",
      "fiscal_period": "2025FY",
      "statement_type": "annual",
      "period_end": "2025-12-31",
      "published_at": "2026-01-23T17:42:00+07:00",
      "xbrl_file": "BBCA-2025FY.xbrl",
      "document_url": "https://www.idx.co.id/...",
      "filing_reference": "official-disclosure-id",
      "currency": "IDR",
      "scale": "unit",
      "account_units": {
        "proven_probable_reserves": "tonne",
        "annual_production": "tonne/year"
      }
    }
  ]
}
```

Required fields are ticker, fiscal period/type, period end, timezone-aware
publication timestamp, XBRL file, and official document URL. A timezone-less
timestamp or publication date before period end is rejected. Unknown XBRL
facts are ignored unless mapped explicitly to a supported taxonomy code.

Optional per-filing fields include `account_map`, `context_id`,
`value_multiplier`, `account_units`, auditor opinion, and going-concern flag.
Per-filing account mappings override the global map.

## Configuration and ingestion

```dotenv
FUNDAMENTALS_PROVIDER=auto
IDX_XBRL_MANIFEST_PATH=C:/authorized/idx-xbrl/manifest.json
```

```bash
python -m src.cli fundamentals sync --tickers BBCA
python -m src.cli features compute-fundamental-ratios --tickers BBCA
python -m src.cli sector compute-disclosed-metrics --tickers BBCA
```

`auto` unions fiscal-period coverage and selects the official XBRL row for a
period whenever present; Yahoo is used only for periods missing from the
archive. Official XBRL statements cannot be overwritten by the fallback.

The official `published_at` becomes `available_at`, with
`available_at_basis=official_idx_publication_timestamp` and the filing
reference retained in raw lineage. Yahoo fallback statements remain clearly
tagged with estimated availability. This makes mixed-source history explicit
instead of pretending all dates have equal quality.

No official archive is bundled with the repository, and no official XBRL rows
have been loaded into the current database. Code readiness must not be reported
as official data coverage until an authorized manifest is configured and a
real ingestion audit is completed.
