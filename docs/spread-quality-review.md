# Spread reporting repair and offline quality review

The private exporter discarded approved `external_close` evidence before calling
the production ledger. A later settlement could therefore disagree with the
apparent inventory. Failed accounting also left an older P&L CSV in the private
repository. Neither condition is a trading-strategy result.

The exporter now preserves complete signed evidence internally for the existing
ledger to validate. It exports only normalized manual-close rows with hashed
identifiers. Rejected evidence yields null economics and a header-only P&L CSV,
never zero profit or a stale total. The production ownership, fingerprint,
reduction-only, settlement and fee checks remain unchanged. A legacy runtime
without manual-close support refuses to calculate P&L when that evidence exists.

`Repair spread private export only` deploys only the exporter. Its preflight
requires the pinned production revision, unchanged trading files, the known
exporter checksum and a private journal replay that exactly matches the existing
production ledger. It backs up the previous exporter and replaces the file
atomically. Public logs contain only pass/fail flags. The existing hourly exporter
publishes the repaired output; no trading worker is restarted or armed. The
observer, manifest, protocol, study window, rules and sizes are not modified.

## Offline tests

Run outside the production process, with an output path outside any git checkout:

```sh
python -m research.spread_quality_review /private/latest.json --out /private/review.json
```

The review measures three separate questions:

- How much could the complete remaining position have received at each recorded
  checkpoint, after estimated exit fees? Own orders are already removed from the
  study's external depth. Multiple lots consume shared depth only once. Partial
  liquidity is reported separately and never valued as a full liquidation.
- How would a fixed $1 entry-cost budget per event have changed this exact set of
  fills? The budget includes entry fees, allocates in time order and never
  recycles proceeds. This proportional sizing sensitivity uses fractional fills;
  it does not reconstruct order placement or inventory feedback. Multiple fills
  in a market disable this simple calculation. Pending costs remain separate.
- How do the already specified shadow exits compare with holding on the same
  settled markets? An exit on a market whose hold baseline is unresolved cannot
  inflate the matched comparison. Existing slippage scenarios remain unchanged.

Coverage includes only horizons whose due time plus 60 seconds has elapsed.
Future checkpoints and a cohort without fills are not failures. Invalid study
accounting prevents an economic review. These analyses are exploratory; none
establishes profitability or changes the prespecified primary study endpoint.

An entry-filter backtest is **not supported** by the current export: recorded
post-fill books are future information relative to entry. Such a test needs
external books recorded immediately before all submitted quotes, including
quotes that do not fill. That additional recording would require a separate,
versioned research proposal; it is not added to the frozen observer here.

Keep inputs and outputs private. Public tests use synthetic fixtures only.
