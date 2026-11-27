# Microstructure feature extraction (research-only)

## Purpose
Turn recorder JSONL market/book/public-trade observations into features and exploratory diagnostics. This pipeline is **not an executable strategy** and does not estimate fill probability or realized P&L.

## Run
```bash
python -m research.microstructure_features --input data/research/live_events.jsonl
```
Outputs under `outputs/microstructure_research/`:
- `features.csv`: one row per book snapshot; book spread/mid, YES/NO displayed depth (1/3/5 levels), imbalance (1/3/5), trailing five-minute public-trade volume/count and side-flow imbalance, time-to-close where metadata exists, forward mid returns at 5 and 15 minutes.
- `hypothesis_diagnostics.csv`: preregistered exploratory feature/target correlations and low/high-third descriptive comparisons.
- `research_summary.json`: input counts, feature row counts, diagnostics and caveat.
- `index.html`: local HTML diagnostics view.

## Definitions / assumptions
- Kalshi book snapshots expose YES bids and NO bids. NO bids are used as a proxy for YES asks via ask = 1 - best NO bid; mid and spread are computed only when both sides exist.
- Depth and imbalance are based on displayed bid-side quantities: YES bids vs NO bids. This is a **proxy**, not a symmetric orderbook depth measurement.
- Public trade flow is computed from `taker_outcome_side`; unknown side values are excluded from side-specific volume, but still included in total public volume.
- Snapshot timestamps are collector-observation time, not exchange book timestamps. Public trades use exchange trade timestamp when provided. Do not treat observed snapshots as synchronous.
- Forward return uses the first later observed book snapshot at least the horizon after the current row; no interpolation.
- Legacy integer cent values and fixed-point dollar strings are normalized. Values of exactly 1 are interpreted as one dollar; this can be ambiguous with legacy 1-cent values, so collectors should prefer explicit dollar fields.
- Descriptive correlations and low/high groups are exploratory. Overlapping forward horizons, repeated markets/games, small samples, market selection and non-synchronous inputs are not adjusted. Do not use this report alone to promote a signal or claim profitability.
- No API credentials, account endpoints, order actions, execution changes, or strategy configuration are touched.

## Research hypotheses
1. Top-of-book and multi-level displayed bid imbalance relate to subsequent mid-price movement.
2. Recent public trade flow imbalance relates to subsequent mid-price movement.
3. Spread and public volume characterize conditions where short-horizon movement differs.
4. Explore 5- and 15-minute horizons; no statistical significance claim is made.

## Next required research step
Collect a fresh, frozen validation cohort and preregister a limited set of primary features, target horizons, event/game-blocked evaluation, and uncertainty method before any strategy decisions.
