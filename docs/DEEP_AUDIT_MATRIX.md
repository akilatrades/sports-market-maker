# Market-maker deep audit matrix

**Living checklist.** The goal is an exchange-grounded and recruiter-reviewable
trading research system—not merely green CI, a positive first settlement,
or the maximum number of simulated trades. **Unverified** below means evidence
has not yet been established, not necessarily that the feature is broken.

| Area | Questions and proof required | Current evidence / gap |
|---|---|---|
| Model validity | Time-split train/evaluation, point-in-time features, no leakage via final games, closing lines or current injuries; Brier/log loss, reliability, calibration by prop type, game-clustered uncertainty | Monthly walk-forward historical study exists; as-of differences from production and 2026–27 robustness remain material |
| Sportsbook reference | Exact game/player/stat/line, vig removal per independent book, freshness at decision time, disagreement and line-move handling | At least two books were logged on the first filled NBA quote; sustained coverage and independence unverified |
| Minutes and lineups | Correct player/game/team IDs, independently published minutes, source timestamp, confirmed (not projected) starting five; block ambiguous/late inputs | New private intent provenance fields in source; initial filled order lacked them; actual vendor availability on server unverified |
| Pricing and selection | Same-time model/market/venue snapshot, known maker fee bounds, after-fee edge, duplicate threshold and correlated prop constraints; pre-register any tuning | Current code uses 2–6h entry and >=3¢ quoted-edge guard; the first fill is not sufficient calibration of the guard |
| Maker execution | Post-only acknowledgment, queue ahead, exchange-side expiration, limit price, maker/taker flag, 5/15/60m executable bid markout and observed fill share | One exchange-confirmed all-maker NBA fill; midpoint favorable but executable bid unchanged; older-order journal expired >2h before tip |
| Order lifecycle | Durable intent, accepted/unknown/rejected, partial and canceled fills, missing pagination, retries/idempotency, exchange reconciliation before resetting capacity | Mechanisms and tests exist; verify continuous operation and aged-order completeness against signed exchange records |
| Economics and inference | Profit per *submitted* order and cost, per fill and settled contract, maker fees, payout, censored nonfills, independent games, adverse selection, drawdown, confidence by day/game | One NBA positive signed settlement; **insufficient** to infer dependable profitability or size |
| Risk and safety | Per-order/game/team/day/lifetime caps, shared NBA/NFL exposure, foreign position veto, loss stop, KILL, downtime/restarts, end-to-end no-double-submit | Guardrails in code; trading activation and exact deployed SHA require separate current proof |
| Operations and security | Explicit deploy SHA, locked worker update, rollback, read-only signed monitoring, host SSH pinning, secret hygiene, no private logs in public Actions | Staged GitHub-to-Droplet code releases and an automated anonymized audit have been exercised; full live health/SLO not yet established |
| Portfolio and communication | 2-minute overview, no blending simulations with real fills, honest negative findings, reproducible commands, screenshots/diagrams, clear ownership and AI disclosure | Case study and navigation updated in this review; continue validating each metric against a versioned experiment and date |

## Evidence needed before any profitability-focused change

1. **Quote-level forward dataset.** For every eligible decision, preserve model
   and sportsbook probability *as known then*, bid/ask, fee schedule, posted
   quote, queue observation, updated source clocks, and skip reason. Include
   signals that were filtered out, or performance will be selection-biased.
2. **Order-by-order exchange trail.** Signed acceptance/expiry, real fills,
   partials, cancels, payments and settlement, linked by owned IDs privately.
   Public dashboards receive only reconciled aggregates and must say when stale.
3. **Cohort analysis.** Segment by strategy version, prop, entry-to-tip bin,
   quote improvement, fee regime, maker status, liquidity and independent game.
   Bootstrap uncertainty by game or slate; track multiple hypotheses tested.
4. **Shadow comparisons before funding.** Compare the frozen baseline against
   later entries, stronger lineup vetoes, alternative queue prices and tighter
   book filters without placing extra real orders. Check *net dollars per
   eligible signal* as well as net cents per filled contract.
5. **Release gate.** After sufficiently broad forward evidence, review a
   specific versioned rule change, tests, independent evaluation and exposure
   impact. Then separately approve funded activation/size changes. No automatic
   capital escalation from a good night.

## Hiring-manager walkthrough

A practical 10-minute demo should follow one signal without showing private
order IDs: **timestamped forecast → independent price comparison → after-fee
quote decision → safety veto or passive NO order → signed fill/settlement →
reconciled return → next hypothesis**.

The strongest interview topics are (a) why the model-pick taker test lost,
(b) how queue priority makes public trade prints optimistic, (c) where the
risk system deliberately refuses to trade, and (d) what would falsify the
maker-side hypothesis. A clear *failure* and the engineering response often
say more than an unverified return projection.

## Non-go criteria

Do not present paper/dry results as cash P&L. Do not use the first NBA winner
to tune a threshold and then count that winner as out-of-sample evidence.
Do not label a provider's expected lineup as confirmed, and do not guess
projected minutes from trailing box scores. Do not assert that an intended
expiry is the actual exchange expiry. Do not call an order fill rate until
closed outcomes and missing data are reconciled. Do not loosen risk caps,
restart trading, or deploy new rules as a consequence of preparing this
review.

See the [two-minute project brief](PROJECT_BRIEF.md), the
[October 21 signed fill audit](NBA_OVERNIGHT_AUDIT_2026-10-21.md), and the
[forward-validation protocol](FORWARD_VALIDATION.md).
