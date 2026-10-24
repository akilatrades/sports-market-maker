# Prediction-market arbitrage: feasibility gate (Oct 24, 2026)

## Decision question

Is there enough **US-accessible, independently verifiable, after-fee and
execution-adjusted arbitrage** to justify a small capital pilot?

No real orders are authorized by this document. The current live NBA, NFL and
spread bots are left unchanged. Read-only research consumes public APIs.

## Existing baseline

- The cross-exchange player-prop scanner under
  `live/compare_polymarket_us.py` already runs every four hours.
- Its October 24, 2026 16:52 UTC snapshot scanned 1,163 NBA and 1,280 NFL
  Kalshi contracts, and returned **zero** strictly matching US Polymarket
  player-prop candidates. The Polymarket US tagged-prop feed was empty, so
  this is a **coverage failure**, NOT proof that the exchange has no props or
  that there are no arbitrage opportunities.
- Do not use international Polymarket order books for an American account.

## New same-exchange ladder probe

`python -m research.arb_ladder_probe` scans five public Kalshi numeric player
threshold series, grouping only markets with the exact same series, event and
player. It checks neighbouring strikes. If a lower threshold is implied by a
higher threshold, the *conditional* payoff floor of YES(lower) + NO(higher) is
$1, provided the exchange's actual resolution rules support that relationship.

It reads two full order books for each positive-looking list-quote pair.
Executable YES asks derive from NO bids and executable NO asks derive from
YES bids. It caps displayed size at ten whole contract pairs and deducts the
standard two taker fees with per-order rounding, then discards time-separated
snapshots over two seconds apart.

**These are not verified opportunities.** Fee multipliers can differ by
market. The two order books are not atomic, available depth can disappear,
the matched contracts might have incompatible settlement conditions, and
read-only data cannot prove our order would fill. Every candidate carries
explicit false flags for verified rules and fills.

The GitHub Actions workflow samples public books and uploads a JSON report as
an artifact. It has read permissions only and uses no account credentials.

## Pre-registered experiment

1. **Coverage (first 48 hours):** Count all matching threshold groups,
   adjacent pairs checked and API failures. If coverage is near zero,
   fix mapping before drawing a profitability conclusion.
2. **Market observation (14 days):** Capture every positive list-price pair
   and depth-confirmed candidate as a timestamped observation. Deduplicate
   repeated snapshots into episodes; count distinct events, usable available
   depth, indicative net dollars and quote persistence. Do not count each
   repeat observation as a separate trade.
3. **Rules validation:** Independently compare the market rule text,
   cancellations, push/void/reschedule, corrections and expiration.
   Unverified relationships are excluded from any arbitrage P&L claim.
4. **Execution stress:** Replay simulated leg placement with delays of
   100/250/500/1000 ms, using logged market updates/trades (to be added).
   A quote remaining visible is not evidence of a real fill. Evaluate
   one-sided adverse exposure separately.
5. **No-go gate:** No funded implementation without multiple distinct
   rule-verified opportunities remaining positive after exact venue fees
   and with sufficient depth under delayed execution, plus an independently
   reviewed procedure for incomplete fills and reconciliation.

The probe currently implements steps 1 and a *snapshot-level* subset of
step 2, **not** rule review, persistence logging, historical queue replay or
actual live execution. Those are explicit follow-on research requirements.

## What to report

- Eligible markets / adjacent pairs: distinguish lack of coverage from
  absence of observed arbitrage.
- Gross candidate episodes, depth-available size, fee-adjusted theoretical
  profit, quote age, evidence of survival after a realistic delay.
- *Separate*: theoretical complete-pair P&L and loss distribution when a
  second leg does not fill. Report fees at actual execution quantity.
- Cost of capital, time to settlement, exchange-specific restrictions.
- A final continue/pivot/stop verdict based on new observations.

The experiment uses no new bankroll and must not modify deployment, secrets,
balances, portfolio limits, order placement or the production dashboard.
