# Production execution audit — October 20, 2026

**Scope:** bounded NFL and NBA one-sided post-only NO trading on Kalshi
Production. This is a directional **passive liquidity-providing** strategy,
not a neutral, two-sided high-frequency market-making system. Do not claim
otherwise on a resume. The production implementation has shared-account
risk controls, but positive net returns have **not** been established.

## Observed baseline — owner-provided DigitalOcean status at 02:21 UTC

- Both production systemd timers: active.
- NBA service: inactive *between scans* (normal for a oneshot worker).
- NFL service: activating *during a scan* (not by itself an error).
- NFL journal: 12 submitted/accepted, 4 recorded fill events, 4
  recorded settlement events; 0 unknown submissions.
- NBA journal: 0 submitted/accepted/fill events, latest scan no candidates.
- NFL latest scan: no eligible candidates. NFL verified data source had a
  recently generated **Week 6** ladder — which is suspect after the Week 6
  Monday game. Model generation formerly chose the oldest *unscored* week,
  not the next *unstarted* game. Delayed upstream finals could therefore
  recreate obsolete model snapshots with fresh timestamps.
- NBA model checksum valid; 312 projections, 1,222 sportsbook rows
  (470 with at least two books) but eligibility still requires timing,
  injury, matching, spread, fee and executable edge.
- The systemd health report is **LOCAL ONLY**. It did not compare current
  journal records to Kalshi or prove profit. No up-to-date live exchange
  fills, amounts or realized P&L were visible in that screenshot.

## What was repaired and verified by regression tests

1. NFL week selection now uses verified *scheduled kickoff* to prevent
   republishing a previous slate with an artificially new model timestamp.
2. NFL's public immutable data bundle retains multiple recent projection
   ladders, so a late old-week refresh does not erase a correct new-week
   model; its existing 36-hour per-probability trading cutoff remains.
3. The private Kalshi account dashboard now includes **fully filled
   historical orders** instead of excluding them, alongside resting,
   expired, partially filled and unknown orders.
4. Real fill timestamps, volume-weighted NO fill price, fees and maker/taker
   counts are derived from authenticated exchange fill IDs. Missing fees,
   fill metadata, or missing archived order statuses are shown as unknown,
   never imputed as zero. Older statuses can be read by signed GET-by-ID.
5. The read-only fill scorecard separates closed-order fill rate, maker
   share, time to first fill and quote-time *model-estimated* edge on orders
   that actually filled. These are **not** realized profits or guaranteed
   favorable queue captures.
6. Bounded, round-robin reads for individual archived orders and public
   trade prints protect the dashboard from unbounded optional telemetry.
   Market prints at/through our price are only *possible contra flow*,
   not a claim that our resting order should have filled.
7. CI now runs Python tests on 3.11 and 3.12, Ruff, shell syntax checks,
   and the private account JavaScript regression. Guarded release scripts
   leave trading paused after a failed post-pull test/preflight instead of
   silently restarting unverified code.

## What still requires REAL exchange evidence

These cannot be established by unit tests or a GitHub commit:

- Signed Kalshi GET reconciliation after the revised release is actually
  deployed, including portfolio **orders, fills and settlements**.
- Proof the current live NFL/NBA scans are completing rather than just
  scheduling. Account data cannot be inferred from a healthy timer.
- Full execution funnel: eligible quotes → placed → exchange accepted →
  maker filled / partially filled / expired / canceled → final payout.
- Queue-age/capture evidence on matched contract and price, plus the actual
  fee schedule and adverse-selection marks 5, 15 and 60 minutes after
  fills. A one-minute price print is not sufficient L2 queue replay.
- Whether the NBA quote source and player/fixture matching perform
  correctly through the first real opening-night entry window.
- Independent out-of-sample calibration of `p_yes` and sportsbook signals,
  after deduplicating correlated player props and excluding stale data.
- Realized per-fill or per-market net P&L must be independently reconciled;
  the displayed *modeled* edge is never counted as profit.

## Release gates (do not conflate with profitability)

- Both source data feeds pass timestamps, checksum, roster/injury and
  season-week matching; unsupported quotes fail closed.
- Local and shared account journals are durable; no unknown submission
  outcomes, no unowned orders, no uncontrolled positions.
- Trading orders remain post-only, idempotent, quote-checked, constrained
  by shared $25 active / $40 daily / $100 lifetime buffers and individual
  cohort $3/order limits.
- An end-to-end signed read-only preflight and completed worker scans are
  observed **on the Droplet after deployment**, not inferred from CI.
- Historical exchange fills are available through the *private* dashboard.
  No private journal, account/order IDs or API credentials are published on
  the public recruiter dashboard.

## Research standard for a credible edge claim

`P(fill | state, quote)` and
`E[net outcome - paid price - fees | fill, state, quote]`
must both be estimated out-of-sample. Observing many fills is not proof of
advantage; informed traders preferentially lift stale favorable quotes.

Report fill selection by source (sportsbook-confirmed vs model-only), edge
bucket, time-before-tip, market family, order lifetime, queue-ahead bucket,
game/player and fill latency. Present confidence intervals or bootstrap by
game rather than pretending each correlated player contract is independent.

No scaling decision should be based on the existing handful of live NFL
fills or zero NBA fills. A portfolio claim like “implemented an
exchange-reconciled passive liquidity strategy with fill-quality and shared
risk controls” is supportable once the updated system is deployed and
verified; **“profitable market maker”** is not presently supportable.
