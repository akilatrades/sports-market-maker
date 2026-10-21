# NBA market-maker readiness and profitability audit — October 21, 2026

**This is a research, code and execution review, not authorization to trade.**
The production setup is currently a directional, post-only, passive-NO
liquidity strategy, not a neutral two-sided market maker. GitHub source
and green CI do not mean funded trading code has been deployed.

## Hard evidence from signed private fill audits (October 21 UTC)

- 9 NBA orders accepted, 1 completely filled, 0 exchange-order unknowns
  in the audited cohort. **Do not call 1/9 the closed-order fill rate:**
  the other order outcomes and censoring are essential.
- The observed fill was 100% maker, within 15 minutes of submission,
  posted 2–6 hours before tip, and its original forecast after-fee edge
  was positive with at least 2 independent books.
- Recorded NO midpoints moved in a favorable direction at 5/15/60 minutes,
  but the **executable NO bid change was zero** in those observations.
  Mark-to-mid is not realized sellable profit.
- One NBA settlement was exchange-verified and positive after ownership
  and fill-cost reconciliation. This is far too little for a profit claim.
- The original filled order was classified as an older/unknown strategy
  generation; its journal expiry was more than two hours **before** tip.
  The currently reviewed v4 source instead writes expiry at scheduled tip,
  but a new authenticated order still needs to prove the deployed behavior.
- Historical projected-minutes verification and confirmed-starter provenance
  **were not recorded for that fill**. We must not reconstruct or assume them.

Evidence: GitHub read-only audit runs
[1](https://github.com/akilatrades/sports-market-maker/actions/runs/39541489414)
and [2](https://github.com/akilatrades/sports-market-maker/actions/runs/39542054076).
These are coarse public summaries, not full private account records.

## Already in reviewed source (must verify exact deployed SHA)

- Durable intent before POST; one new maker order per pass; exact quote and
  fee checks before submission; ownership reconciliation across account shards.
- New 2–6h entries, resting until **scheduled tip** unless invalidated by
  verified news, probability, maker passivity or availability.
- Estimated maker fee bounded at entry, with >=3c remaining edge for
  new and retained orders; a second price-improvement tick disabled.
- Limited submitted allowance, active reservation, game/team concentration,
  realized daily/cumulative loss breakers and independent shared NBA/NFL caps.
- Strict source timestamp/checksum/roster/fixture verification; two sportsbook
  quotes on exact line when required, with no one-book consensus claim.
- Late 30m–2h **shadow only**, not authorized to submit. The approved
  licensed projected-minute and confirmed-starter feeds are not proven
  configured and reliably available.

## High-priority, low-risk code improvement in this review

For future *private* NBA order intents, log the originally observed:

- Independent minutes source + minutes value, **distinct from historical** EW
  baseline; any invalid/missing observation recorded as null
- Confirmed-starting-five status and whether this individual was named,
  treating a predicted starter as unverified
- Timestamp when the licensed response was **fetched**, distinctly labeled
  so it is never mistaken for vendor publication time
- Sportsbook exact-line probability and update time, Kalshi bid/ask,
  model probability and model-input build time
- Exchange expiry policy, quote verification clock and model/strategy version

This only adds as-of telemetry to a private journal; it never expands entry
eligibility, sizes, budgets, or trading activity.

## Profit improvement candidates — evaluate, do NOT just switch on

| Priority | Hypothesis | Controlled evidence needed | Failure mode |
|---|---|---|---|
| P0 | Independent projected minutes & confirmed starters reduce bad rotation calls | Licensed and timestamped pregame source, player-ID joins, missing-source veto, strictly as-of 2026–27 forward records | Free ESPN roster is not tonight's starting five; historical minutes aren't projected minutes |
| P0 | Tipoff expiry captures more real maker fills than old early expiry | Signed *new v4* accepted orders + verified exchange expiration, queue/contra timestamps and actual fills | More adverse selection from late news; expired journal intent != exchange acceptance |
| P0 | Quote-time edge predicts net settlement return after costs | Every accepted/rejected quote cohort linked to owned fill IDs, trade fees, eventual payouts and independent games | Selection bias: reporting only profitable filled trades |
| P0 | 3c entry/retention filter controls noise vs fill opportunity | Prospective shadow control cohorts from same timestamps with calibration; no lookahead | Filtering on one winner or optimized backtests |
| P1 | Quote improvement or queue priority lifts **net dollars per quote**, not only fill rate | Record venue spread/queue position/YES-taker prints/observed capture; compare in a pre-registered shadow trial | Paying one more cent for unwanted fills |
| P1 | Model improves out-of-sample prediction of binary stat lines | Forward log loss, Brier, reliability/decile calibration by stat, player, line, minutes, injury status and game | 2025–26 training/2026–27 roster regime change, leakage |
| P1 | Multi-book probabilities outperform the standalone historical model | Timestamped de-vig exact player/stat/line, 2+ independent books, time vs news and true holdout | Stale or correlated books, wrong or alternate lines |
| P1 | Partial fills/cancels can reclaim active allowance safely | Signed order detail, complete pagination, owned fills/positions/settlements; ensure no double spend | A cancel acknowledgment may conceal an earlier partial fill |
| P2 | Expanded markets (other NBA props / tennis / NFL) diversify | Separate pre-registered cohort, fee schedule, liquidity/queue evidence and held-out results | Combining different market microstructure into fake significance |
| P2 | More stake/throughput improves monthly net dollar expectation | Net per **submitted** cost and per independent game, fill capacity, drawdowns, correlated max loss | One successful settlement is not a bankroll sizing rule |

## Review gates before changing live funded behavior

1. Verify exact deployed SHA + timer/arm state via signed/read-only
   production status. GitHub merged tests are **not** deployment proof.
2. Verify a fresh NBA source bundle, current schedule and provider licensing.
   Absent independently projected minutes/starter confirmations must stay
   explicitly unverified, particularly around tip.
3. Verify exchange-side order expiration on a *new* v4 order, rather than
   relying only on the journal intent or old historical policy.
4. Inspect the complete outcome denominator: accepted, resting, partially
   filled, fully filled, expired and unknown, by strategy generation.
5. Compare 5/15/60-min **executable** markouts and final net settlement
   P&L, not just midpoint movement; attribute fees without inventing zero.
6. Require a frozen hypothesis, a forward test, several independent games
   and a documented stop rule before optimizing parameters or raising size.

**Explicit non-go decisions:** no unattended funded activation, no loosening
loss limits, no forced live fills, no 30m–2h live entries, no invented source
availability, no claims of durable profitability from the first settlement.

**Morning handoff:** inspect this PR's CI, check whether telemetry has been
merged/deployed (separate decisions), retrieve a fresh signed read-only
fill/health audit, and identify blockers for tomorrow's slate.
