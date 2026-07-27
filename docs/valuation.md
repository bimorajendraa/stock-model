# Valuation (Tahap 5, spec sections 8/10)

Status: own-history multiples, same-sector peer multiples, and an optional
free-cash-flow DCF are implemented in `src/valuation/`. Results are stored in
`valuation_results`; component inputs and sensitivity details remain in the
JSONB audit payload.

## Methods

### Own-history P/E and P/B

The latest positive EPS or book value per share is multiplied by the
25th/50th/75th percentile of the company's own historical P/E or P/B. Each
method needs at least three positive historical multiple observations. This
answers “cheap or expensive relative to its own observed history,” not
intrinsic value.

### Same-sector peer P/E and P/B

The same per-share inputs are multiplied by the 25th/50th/75th percentile of
the latest usable multiple for other active equities with the same
`sector_registry_id`. The company itself is excluded and at least three
positive peer observations are required. A bank is therefore never silently
compared with a miner. Peer count and percentiles are recorded in
`sensitivity.peer_pe_method` / `peer_pb_method`.

### Free-cash-flow DCF

DCF uses the latest annual positive `free_cash_flow`, plus cash, debt, and
shares outstanding from the same point-in-time statement snapshot:

`equity value = PV(projected FCF) + PV(terminal value) + cash - debt`

`fair value/share = equity value / shares outstanding`

The default projection horizon is five years. The method produces:

- base: configured discount, near-term growth, and terminal growth rates;
- bear: discount +1 percentage point, both growth rates -1 point;
- bull: discount -1 point, both growth rates +1 point;
- a 3x3 grid over discount and near-term growth at ±1 point, holding terminal
  growth at its configured base.

DCF is deliberately absent unless all three assumptions are supplied. It also
refuses non-positive FCF/shares and any case where discount rate is not above
terminal growth. Configure it with:

```dotenv
DCF_DISCOUNT_RATE=0.12
DCF_NEAR_TERM_GROWTH_RATE=0.05
DCF_TERMINAL_GROWTH_RATE=0.03
DCF_PROJECTION_YEARS=5
```

These are explicit operator assumptions, not inferred or disguised as market
facts. A future macro-to-WACC policy can replace them only after that policy is
documented and validated.

## Point-in-time and method combination

For an `as_of_date`, ratios and statement items are filtered by
`available_at <= end-of-day UTC`, and market prices by `date <= as_of_date`.
This prevents future filings or prices from entering a historical valuation.
Every available method receives equal weight per bear/base/bull scenario;
`fair_value_conservative` is the minimum available bear estimate. Missing
methods remain missing rather than contributing zeros.

`data_quality_score` combines historical multiple depth with method coverage;
it is an input-completeness indicator, not statistical confidence or a promise
of forecast accuracy.

## CLI and current rollout status

```bash
python -m src.cli valuation compute --tickers BBCA,TLKM
python -m src.cli valuation compute --all --only-eligible
```

The previously recorded production run contains 619 own-history valuations.
Peer and DCF paths now pass deterministic unit and PostgreSQL integration
tests, but production rows have not been recomputed during this change. DCF
will remain absent there until the environment contains all three assumptions.

## Limitations

- Peer estimates inherit sector-classification quality and can be distorted by
  different accounting periods, business mixes, or temporary earnings.
- Own-history multiples are partly circular because their historical ranges
  contain market prices, and current fundamental history is short.
- The DCF is a transparent steady-growth model, not a detailed analyst forecast
  by segment; sensitivity is essential and assumptions must be reviewed.
- No valuation method is a recommendation or guarantee of return.
