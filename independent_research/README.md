# Independent prediction-market backtests

Results as of 2026-10-29. This branch is a separate research project, not a
funded strategy change. There are zero validated trading-return backtests.
It reads public data only and does not use trading credentials or account APIs.

## Findings

| Family | Test | Result |
|---|---|---|
| TSA | 114 daily forecasts, July 1–October 22, 2026 | Model MAE 127,266 versus 150,347 for the initial four-week weekday baseline; primary improvement CI includes zero. |
| TSA robustness | Same weekday 364 days earlier | MAE 116,574, making our model 9.2% worse. Exploratory comparison added after the primary scores; not a new holdout. |
| Weather | 272 dates per airport, January–September 2026 | Fixed 60-day bias correction reduces GFS grid-maximum error by 21.9% at JFK but 1.6% at ORD. A grid maximum is an imperfect daily-high forecast. |
| CPI | 31 monthly outcomes, January 2024–September 2026 | Trailing released-error correction raises MAE from 0.0723 to 0.0825 percentage points, 14.0% worse. October/November 2025 substitute labels excluded. |
| Price consistency | 933,580 overlapping comparisons | 27 raw positive comparisons, 12 events; all 1–2 cents. None remains positive under one-contract standard taker-fee stress. Seven survive the unrounded fee floor before slippage; depth/execution unverified. |
| SPX relative value | Data audit | Matched SPXW option bid/ask history and precise settlement mapping missing; not backtested. |
| Politics/mentions/entertainment | Scope/data audit | No recurring target and point-in-time signal dataset constructed; not backtested. |
| Very short crypto/gold | Data audit | Synchronized underlying feeds, receipt timestamps and depth missing; not backtested. |

Forecast accuracy is not trading profit. The raw price comparisons are not
independent trades. They do not certify exceptional settlement rules,
historical fee waivers, queue position, concurrent fills or unwind losses.
TSA inputs use dated third-party snapshots; target labels are first observed
in that archive, not certified first official publication. Weather airport
observations are not silently treated as a different exchange station.

## Files and reproduction

- `PROTOCOL.md`: fixed initial models and evaluation windows.
- `MACRO_PROTOCOL.md`: separate CPI component specification, written before
  inspecting the archived nowcast values or scores.
- `collect.py`: bounded public GET collection, source URLs and SHA256 hashes.
- `repair_weather.py`: serial retries for missing weather months.
- `analyze.py`: fixed forecast tests and historical price screen.
- `finalize.py`: explicitly exploratory annual TSA benchmark, fee stress and
  compressed byte-identical transfer of the public macro archive.
- `macro_test.py`: CPI forecast comparison and substitution exclusions.
- `test_independent_research.py`: future-snapshot mutation, price-schema,
  pre-close/empty-book and forbidden-endpoint guards.
- `../independent_results/`: archived inputs, predictions, skips, results,
  source hashes and sensitivity calculations.

Install pandas 2.2.3, numpy 2.1.3 and scipy 1.14.1. From the repository root:

```sh
python -m unittest discover -s independent_research -p 'test_*.py' -v
python independent_research/analyze.py
python independent_research/finalize.py
python independent_research/macro_test.py
```

No new money should be committed on these results. The next stage requires
stronger settlement-matched benchmarks, daily publication records and actual
timestamped bid/ask depth, followed by a genuinely new evaluation sample.
