# Execution improvement V2 — staged research, October 2026

The current production strategy remains a bounded, one-sided, post-only
NO liquidity experiment. These improvements do **not** expand live risk
limits or change actual order prices.

## Changes committed

1. **NBA candidate funnel:** each scan records number of available markets,
   roster/tip-verified markets, markets in the 2–6 hour entry window,
   supported prop series, candidates after the book/model/spread strategy,
   NO-side candidates, sane estimated-edge candidates, and candidates not
   previously attempted. This distinguishes *no qualifying signal* from
   *a valid signal denied by the execution/risk checks*. Numbers are local
   diagnostics, not supposed additional trades.
2. **Dry-run isolation:** NBA read-only scans cannot overwrite the
   last real production scan status. An active timer alone is not proof
   that a recent funded-account worker succeeded.
3. **Order-specific quoted edge:** actual exchange fills are linked to
   their own accepted order IDs, rather than whichever signal was most
   recently associated with the same Kalshi ticker. Repeated quotes
   cannot contaminate the execution scorecard's historical model-edge
   attribution. Unknown fill attribution stays unknown.
4. **Shadow quote ladder:** for up to five current qualifying signals in
   each NFL/NBA scan, calculate a baseline NO maker quote and up to two
   additional tick improvements. A shadow alternative is shown only
   if it remains strictly passive at the *observed* YES bid, stays in
   the 10–90¢ allowed price range, and leaves at least 3¢/contract of
   estimated edge after accounting for the additional price. It cannot
   send, cancel or replace Kalshi orders. Output is kept in private
   `last_scan.json` under `quote_research`.

## What the research does NOT claim

- An improved price is **not** automatically optimal or profitable.
- A quote-price snapshot is **not** proof of our live queue position.
- Adding one tick can reduce the modeled return; better fill probability
  must be measured empirically using actual resting orders and public
  trade flow before live quote selection changes.
- Neither these changes nor passing CI establish a live edge.

## Next measurement

For accepted orders, combine the signed Kalshi order/fill history, price,
fee, fill latency, queue observations and settlement P&L. Compare price
improvements in a shadow replay first, accounting for the exact observed
resting lifetime, queue priority, game/player correlation and missed-fill
censoring. Only change live pricing following a separate reviewed
out-of-sample analysis, not just more fills.

Deployment boundary: GitHub commits do not update the already-running
DigitalOcean Droplet by themselves; current account and worker health are
not accessible through GitHub CI.
