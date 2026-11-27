# NBA Microstructure Prospective Validation Protocol (v1)

**Protocol frozen:** 2026-11-27 UTC  
**Cohort start:** 2026-11-28 00:00 UTC (no pre-start data admitted)  
**Planned cohort end:** 2026-12-28 00:00 UTC  
**Status:** prospective validation / read-only research  
**Protocol ID:** `nba-microstructure-prospective-v1`

## Why this study

The existing 2025-26 replay and 2026 reports are exploratory and in-sample. They motivated candidate hypotheses but are not independent evidence. This protocol creates a new prospective observation cohort using the public read-only recorder. No strategy, trading, account, or order endpoint is involved.

## Data and scope

Use only recorder events collected on/after the cohort start:
- Series: `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, `KXNBA3PT`.
- Collector: public market metadata, orderbook snapshots and public trade tape.
- Scheduled collection cadence: 15-minute GitHub Actions runs; within-run polling is 60 seconds.
- Scope cap: up to 5 markets per series per run (volume-ranked by collector).
- Snapshots are collector-observation timestamps, not exchange-synchronized timestamps.
- Public tape is not our own fill record and cannot prove queue position or execution.

The recorder stores data as JSONL in workflow artifacts. Artifact retention must cover the cohort and analysis; researchers must download/merge artifacts, deduplicate public trade IDs and keep provenance. If data gaps, collector changes, or retention issues invalidate coverage, report the cohort as incomplete instead of silently filling it.

## Primary hypotheses (fixed)

1. **Book imbalance:** top-level YES-vs-NO displayed bid-depth imbalance has predictive association with the subsequent 5-minute observed mid-price change.
2. **Public trade flow:** trailing 5-minute public YES-vs-NO trade-flow imbalance has predictive association with subsequent 5-minute observed mid-price change.
3. **Secondary horizon:** repeat the two primary features at 15-minute target horizon, explicitly secondary.
4. **Spread context:** spread is descriptive only, not a primary hypothesis.

The primary hypothesis is association, not a claim of tradable edge. Direction is two-sided (association); do not change to a directional hypothesis after seeing data.

## Unit, exclusions, and sampling

- Unit of analysis: market-level observation pairs; do not treat overlapping snapshots as independent.
- For primary analysis, retain at most one eligible observation per market per 5-minute UTC bin (first valid snapshot in bin), then use event/market clustered uncertainty; markets sharing an event must be clustered together when event identifiers are available.
- Require both book sides for mid-price; reject crossed/invalid books and nonfinite feature/target pairs.
- Forward target: first later observed mid at least 5 minutes and no more than 10 minutes after the selected snapshot; for secondary 15-minute target use 15–30-minute bounded gap.
- Exclude rows without valid target observation. Report coverage and target gaps, not just complete-case statistics.
- Deduplicate public trades by trade ID; if trade ID is missing, count separately as undeduplicable and report it.

## Frozen analysis

- Report sample counts, unique markets/events, date coverage, missingness, target-gap distribution and collector errors where available.
- Primary metrics: Spearman correlation and Pearson correlation between feature and target; high-vs-low feature quantile return difference (thirds) as descriptive only.
- Uncertainty: bootstrap by event (not snapshot) with fixed seed and 2,000 resamples; report 95% intervals. If event clusters are too few, mark inferential results underpowered.
- Keep 5-minute targets primary. 15-minute results are secondary. No searching other features, bin cutoffs, series filters, or horizons and then promoting the best result.
- Report all four series separately and pooled; pooled results must not hide contradictory series-level results.
- No p-value/significance fishing or strategy optimization. If multiple primary features are tested, clearly label them and use Holm adjustment for the two primary feature tests.

## Minimum coverage and interpretation gate

Treat the cohort as **inconclusive** if any of the following:
- fewer than 20 distinct event clusters with usable primary targets;
- fewer than 500 valid primary feature-target pairs overall;
- fewer than 100 valid pairs in at least 2 of the 4 series;
- coverage or data gaps prevent the cohort period from being characterized.

A feature may be called a **candidate predictive association** only if its pooled effect's event-bootstrap 95% interval excludes zero, Holm-adjusted result passes 5%, at least two series show the same direction, and the result is not driven by one event (report leave-one-event-out sensitivity). This is still not a trading edge.

## What this study cannot establish

- executable returns or positive expected P&L;
- maker fill probability, queue priority, latency, cancellation behavior, or personal fills;
- causal effect of our orders on the book;
- performance of the historical NBA NO-order replay or sizing rules;
- value after fees, slippage, adverse selection, or position risk.

## Decision rules

- **Incomplete/inconclusive:** coverage or minimum sample gate fails; continue collecting or redesign only in a new protocol version.
- **No robust association:** report null/weak findings; do not optimize on this cohort.
- **Candidate association:** only authorize a separate preregistered study of executable quote/fill economics. No live deployment from this result.

## Reproducibility and provenance

Archive the merged JSONL input (or a content hash plus access-controlled durable copy), artifact run IDs, collector version/commit, merge/dedup procedure, protocol version, and generated report. Any deviation must be logged before analysis. The prospective cohort must not be backfilled with older snapshots.
