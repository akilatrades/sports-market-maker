# Live research data collection (read-only)

## What this adds
- `research/live_kalshi_collector.py`: polls public Kalshi REST markets, current order books, and public trade tape for explicitly specified series tickers.
- `research/research_monitor.py`: builds a local HTML count/coverage dashboard from recorder JSONL.

No auth keys are read. No private account fills are fetched. No order placement/cancellation endpoints are used. Public prints are labeled public trade records—not your own fills.

**Important:** Kalshi REST current order books are snapshots with no exchange timestamp. Collector stores collection time; snapshots cannot reconstruct historical queue priority or actual fill certainty.

## Run a single sample collection
Choose a small series scope first; market cap is 5–10 and collection cadence should be conservative.

```bash
python -m research.live_kalshi_collector --series KXNBA --max-markets 5 --once
```

## Run continuously (conservative polling)
```bash
python -m research.live_kalshi_collector --series KXNBA --max-markets 10 --interval 60
```

Use one or more explicit series tickers separated by commas. Keep interval at least 15 seconds. It polls open markets per series, chooses highest volume (where volume parses), records market/book snapshots and deduplicates public trade IDs within process memory. Restarting the process resets the in-memory trade-ID cache, so historical prints may repeat across restarts; use trade_id for downstream deduplication.

## Dashboard
```bash
python -m research.research_monitor
```
Open `outputs/research_monitor/index.html` locally. Counts are coverage diagnostics, not performance stats. Actual order-attempt and own-fill data are not collected by this public collector.

## Next integration
Add a read-only account adapter (separate credential/permission review) to emit order attempts, acknowledgements, cancellations, and personal fills. Do not wire the data collector into execution logic.

## Scheduled collection (GitHub Actions)

A workflow is included to collect four documented NBA prop series every 15 minutes. Each run records for up to 12 minutes, caps at 5 markets per series, polls every 60 seconds, builds the monitor, and uploads a 14-day artifact. It is read-only. The schedule becomes active only after this PR is merged; use Actions > Collect sports market research data > Run workflow for a manual run.

Series scope: `KXNBAPTS`, `KXNBAREB`, `KXNBAAST`, `KXNBA3PT`. This is a starting cohort, not all sports markets.
