# Independent prediction-market backtests, v1

Locked before retrieving outcomes on 2026-10-29. This is separate from all
funded bots, sports research and the frozen spread observer. It reads public
data only. No deployment, account API, trading credential or order endpoint.

## Scope and evidence labels

Assess all seven families in the independent October 28 research brief.
Report data rejection as a rejection, not a zero-return backtest.

1. S&P digital/range valuation: requires matching timestamped SPXW bid/ask
   curves, index reference and exchange quotes. Without options data this
   strategy cannot be backtested. Do not substitute a stock return model.
2. TSA: forecast-only rolling test using archived database snapshots, not
   today's historical table as past features. Each target uses the most recent
   commit strictly before 12:00 UTC on the preceding day. Require snapshot age
   at most 10 days. Baseline is the mean of the most recent four observations
   of the target weekday. Challenger predicts the log ratio to 364 days ago
   with a fixed ridge regression: intercept, linear time trend, weekday,
   three annual Fourier pairs, and fixed US holiday windows. Trailing 730
   training days; regularization fixed at 10, intercept unpenalized. Data prior
   to July 1, 2026 are development; July 1–October 22, 2026 is the locked
   retrospective evaluation period. Outcomes use the first snapshot containing
   a count, whose release identity is NOT verified. This is a public archive
   proxy; it cannot establish exchange settlement returns.
3. Payout consistency: sample the final 30 settled events available on or
   before October 27, 2026 for prespecified numerical series. Retain all strikes,
   including zero-volume markets. Multiple events on one day are not independent
   days; report both counts. Compare bid/ask candle closes at a common
   timestamp, never independent intrabar lows. Report price inconsistencies
   only: candles lack historical depth, quote age and atomic execution.
4. Weather: New York JFK and Chicago ORD chosen before outcomes. Archived
   00 UTC GFS MOS guidance, assuming available by 06 UTC; score the max of
   forecast grid temperatures in the next local calendar day against NWS CLI
   daily high. First examine grid coverage and station/day mapping. Baseline
   is raw forecast; challenger adds trailing 60-day mean bias, requiring at
   least 30 targets whose date is at least two days before today's target.
   Develop in 2025, evaluate January–September 2026. Forecast-only component
   test; exact exchange resolution, receipt times and trading remain separate.
5. Macro: inspect Cleveland Fed archived nowcasts and first-release labels.
   No use of revised FRED observations as real-time features. Reject if an
   actual vintage history cannot be retrieved and mapped.
6. Politics/mentions/entertainment: assess data/schema. No pooled headline
   strategy without exact recurring target, a frozen signal and dated inputs.
7. Very-short crypto/gold: assess availability. No latency/lead-lag P&L from
   hourly bars or unsynchronized prices.

## Evaluation safeguards

Forecast scores are not trading returns. No simulated fill without executable
ask/depth evidence. Fee rates and contract rules need contemporaneous versions.
No repeated tuning on the evaluation window. Forecast comparisons use paired
event errors, block-bootstrap intervals (seven-day blocks, 2,000 resamples,
seed 20261029); apply Holm adjustment if claiming success across families.
Test windows and models are not changed after seeing results. Archive
source URLs, hashes, timestamps, raw responses, skipped events and failures.

No family is eligible for live trading from these preliminary tests. A new,
untouched forward sample is required after model/data choices are finalized.
