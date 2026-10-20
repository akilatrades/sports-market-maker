# NBA v3 proposed: longer resting orders plus bounded higher throughput

**Status:** Code pushed for review, **not** a live deployment or approval to trade.
The existing 30-day v2 protocol and exchange ledger remain unchanged.

## Why
The opening-night pilot's one-hour expiration was a protective engineering
assumption, not a Kalshi exchange requirement or a validated optimal lifetime.
The historical simulator contains possible late fills, but it did **not**
replicate production queue priority, this worker's early cutoff or cancellation
logic. This change is an execution hypothesis, **not** proof of profitability.

## Proposed v3 behavior
- New NBA post-only NO orders keep their original price and have exchange-side
  `expiration_time = verified tip - 2 hours`, subject to the existing verified
  **2–6 hour** entry window. Maximum possible resting time is about four hours,
  rather than one. **Nothing rests through tip-off or indefinitely.**
- Every five-minute worker cycle checks existing resting orders using the
  latest verified player/roster/injury context, fresh sportsbook probability,
  Kalshi YES book, position and risk reconciliation, and fee metadata.
- Original signed order price and quantity, not a newly optimized price, are
  used for the remaining-edge calculation:
  `1 - P(YES now) - original NO price - refreshed maker fee bound per contract`.
  If after-fee expected edge is below **3 cents per contract**, or the original
  maker quote is no longer passive, the worker cancels the resting remainder.
- A formerly sportsbook-confirmed order cannot switch silently to a
  model-only probability because book data went missing. Unverifiable identity,
  unknown original order provenance, or GET/fee errors fail closed: no new
  entries; exchange-side expirations remain as the backstop.
- **Larger, bounded NBA throughput limits:** $4 per order, $12 per game,
  $8 per team, up to four attempted orders per game, eight contracts per order,
  $20 active, $35 NBA submitted per day, **$75 NBA cumulative submitted**.
  These materially increase risk versus v2 and must be approved with a clean
  account preflight; they are not automatically activated by merging this PR.
  The separate shared NFL+NBA caps still limit the whole account to **$25
  active, $40 daily submitted and $100 cumulative submitted**. Those caps were
  **not raised**. No retry/repost of a previously attempted ticker.
  A confirmed zero-fill expiry can release *active exposure* but cannot
  restore either cumulative or daily submission allowances.
- The scan now records **named individual budget blockers**, instead of the
  undifferentiated `risk_budget`, after attempting to shrink contract size.
  This helps attribute missed orders to game, team, daily, active or shared
  account admission limits without relaxing unrelated safeguards.
- An order already accepted under v2 cannot have its expiration extended by
  merging this code. It is also not retroactively reentered.

## Research / validation boundary
Log the new policy as strategy version `nba-no-v3-long-resting-throughput`. Do not
combine v2 and v3 trades into one edge estimate. Compare the two cohorts by
independent games, quote-time edges, order lifetime, queue progress, full/partial
fills, no-fill closings, 5/15/60-minute markouts, and reconciled settlement P&L
after actual fees. More fills can be worse fills if they arrive after material
new information. Even the enlarged $75 cumulative submission allowance is far too small
for proof of a durable trading edge. Extra order submissions and higher
fill rates are not necessarily profitable.

## Manual release gate
Before deploying or enabling v3 on the live Droplet:
1. Obtain passing formatting, unit, live-worker, integration and account
   reconciliation tests on the exact branch/commit. Resolve unrelated CI
   failures or document a focused equivalent test run.
2. Compare existing NBA accepted/resting orders and budget with the signed,
   **read-only** exchange account. Explicitly resolve every unknown order.
   Require **zero resting v2 NBA orders** before v3 activation so the new
   cancellation policy never silently changes an already-posted v2 order.
3. Verify systemd worker revision, model/books/injury source timestamps,
   account/shard funding, shared NFL account locks, and Kill switch.
4. Require explicit owner authorization for v3's **increased limits**, any
   additional funded-account exposure and a newly labeled analysis cohort.
   This PR is code, not an instruction to change active risk automatically.
   No automatic journal reset, crediting of old cancellations, or deposit.

This GitHub change does not touch the live Kalshi account, cancel a resting
order, rearm a worker, or deploy the Droplet.
