# NBA v3 safety, minutes, and execution audit — October 20, 2026

**Release decision: DO NOT DEPLOY THIS BRANCH TO THE FUNDED ACCOUNT TONIGHT.**
This work fixes some data-quality and execution-policy inconsistencies but does
not establish a better calibrated 2026–27 NBA model, profitable real fills, or
an adequately informed late-lineup strategy. CI passing is not live validation.

## Changes implemented and tested

- Preserve the existing historical player-minute features and expose
  `historical_minutes_baseline`, `last_game_minutes`,
  `recent_start_rate`, `minutes_estimate_source=prior_games_only`,
  `lineup_confirmation_status=unverified`. These are NOT an external pregame
  minutes projection or a confirmed starting lineup.
- When the current ESPN injury feed explicitly states a minutes restriction
  in `shortComment`, veto the player. Keep fail-closed roster, injury, schedule,
  season/role-change and sportsbook requirements.
- Check that optional historical minutes data are finite and between 0 and 48.
  Missing optional fields in old bundles remain backward-compatible.
- An inconsistency in v3 caused 0–3c positive-edge accepted orders to be
  canceled at the next scan using a 3c retention requirement. The branch
  matches retention to the current entry `net_edge > 0` admission rule;
  optional 1c quote improvement still requires 3c post-improvement.
  **This policy choice is not proven optimal for fills/profitability**.
- Added regression coverage; no production shard, trading flags, position
  journals, canceled orders, or deposits touched.

## Offline public-print sensitivity replay

Reproduction:
`python -m research.nba_quote_time_comparison`

Inputs: frozen 2025–26 historical NO-model snapshot, original quoted maker
prices and public trade prints for points/assists/rebounds/three-pointers.
The script computes a complete historical quote denominator instead of
measuring filled-only profit. Duplicates by ticker are removed, and clustering
for the t statistic is at the game level. These are **hypothetical
print-fill** conditions, not exchange-confirmed fills.

| Last resting time before tip | Model edge filter | Eligible quotes | Possible print fill rate | Hypothetical cents per eligible order |
|---|---|---:|---:|---:|
| 2h (current production cutoff) | 0c | 34,756 | 39.02% | +1.207 |
| 1h | 0c | 34,756 | 48.11% | +1.392 |
| 30min | 0c | 34,756 | 52.77% | +1.555 |
| tip | 0c | 34,756 | 58.59% | +1.776 |
| 2h | 3c | 24,312 | 39.80% | +1.379 |
| 1h | 3c | 24,312 | 48.33% | +1.535 |
| 30min | 3c | 24,312 | 52.67% | +1.748 |
| tip | 3c | 24,312 | 58.14% | +2.014 |

The 3c filter is applied to **historical model edge**, not a contemporaneous
sportsbook-vetoed/live fee-bound order. Cutoff experiments are a post-hoc
comparison on reused historical data. Actual queues and opponent order flow
would change if we submitted the quote, and early- versus late-news adverse
selection is not reproduced. Results cannot justify automatically extending
tonight's live cutoff or raising risk.

## Major missing components

1. **Trusted pregame minutes forecasts:** a historical EWMA playing-minutes
   feature is not a verified tonight-specific projection. ESPN's injury notes
   may expose explicit restrictions; their absence is *not* proof of no cap.
   Need a rights-compatible and stable source with timestamps, player ID,
   estimated minutes, reliability indicator and safe stale/missing fallback.
2. **Confirmed starting lineups:** ESPN roster membership is not a
   confirmed pregame starting five. The code explicitly labels lineup status
   unverified. No trusted timestamped lineup provider is connected.
3. **Prospective validation:** historical 2025–26 possible fills and old
   sportsbook-derived prices do not prove the updated NBA model for 2026–27,
   particularly season-opening roster changes or tonight's injuries.
4. **Live fill mechanics:** need real Kalshi accepted order IDs, queue
   position over time, opposing prints during each resting interval, partial
   fills, cancellation reasons, fee and markout attribution on *all* orders.
   A public print at the limit price is not proof our queued order filled.
5. **New entry window:** the current 2–6h entry window ends before late
   lineup confirmations. A late-entry cohort would require new source,
   re-estimated probabilities, cancellation responsiveness and a fully
   separate prospective study.

## Recommended decision

Keep funded-account risk and the currently deployed v3 unchanged until
we have a reliable timestamped minutes and confirmed-lineup source and
can perform a live staged trial. Separately instrument real orders and
run a prospective paper trial for 1h/30min/tip expirations before changing
the funded worker. Do not cite these simulated cents as realized ROI,
real deposits or a validated income strategy.

Workflow run: https://github.com/akilatrades/sports-market-maker/actions/runs/39499688858
PR: https://github.com/akilatrades/sports-market-maker/pull/35
