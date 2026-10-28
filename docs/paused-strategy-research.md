# Research while funded spread trading is paused

Owner authorized October 28, 2026. Funded spread entries stay stopped. No order
creation, cancellation, liquidation, worker start/restart, arm-marker change,
funded rule change or size increase is part of this release.

The original spread protocol, code identity, October 25 start, November 24
enrollment end and December 1 settlement-follow-up end remain unchanged. The
owner pause is an interruption to funded enrollment, not uninterrupted live
execution. The isolated entry recorder and NBA equal-size v1 also remain pinned.

## Accounting first

An independent signed GET reconciliation refreshes every five minutes while the
worker is paused. It matches exchange fills to accepted spread orders and only
previously approved, fingerprinted manual closes. It reconciles FIFO pair cash,
actual fees, remaining position quantities and actual settlement credits.
Unrecognized account activity, missing signed history or mismatched positions
blocks the aggregate P&L. Missing data is never a zero.

For a scalar settlement, require the signed settlement's YES/NO quantities to
match remaining owned lots and the current position to be flat. Report its
actual credited cash; do not force a YES/NO outcome or manufacture a per-contract
payout. This produces a separate accounting resolution, leaving the original
study's scalar exclusion and hypothetical exit comparison untouched. The legacy
worker journal/dashboard can still lag while paused; the independent report is
the current reconciliation source, with an explicit timestamp and scope.

## Separate spread paper execution protocol

`spread-paper-execution-v1` starts on first successful initialization. It shares
the existing November 24 enrollment deadline and December 1 follow-up deadline;
neither is extended. Existing funded events are excluded. Pin its own manifest
and implementation before entries, in `/home/trader/spread-paper-execution`.

Read the original survey database in SQLite read-only mode. Choose candidates
by ticker, independent of outcome and forecast; log ineligibility and capacity
skips. This is a bounded sample, not every funded v3 opportunity. At most eight
markets are observed concurrently, with at most two new markets per minute.
One quote per market over this study, one contract per side, and a common $5
gross cash-plus-fee opportunity budget per game. Never recycle released cash or
backfill filtered opportunities. Different series with the same exchange event
suffix share a budget. These restrictions intentionally differ from funded
v3's five-contract orders, repeated quotes and portfolio capacity.

Quote one cent inside a newly read two-sided spread of at least eight cents.
Both quotes must be 2–98 cents, the event start at least 85 minutes away, and the
book request at most 20 seconds before the virtual order. Use signed account
orders before and after sampling to remove own depth only if unchanged.

Entry ablations: unchanged 65-minute quote, external full-quantity depth with
immediate exit gap at most five cents including fee bounds, 15-minute expiry,
and both screens. Cross each with holding versus the existing fixed exit rule:
first 10/30/60-minute pregame checkpoint with a bid ten cents above entry; one
attempt, shared available depth, remainder held. A due checkpoint counts only
after its 60-second allowance. Missing observations are unknown, not failed
trades or invented exits. Books are collected prospectively even though fill
reconstruction runs after expiry.

Two public-print fill sensitivities: opposite-taker strict trade-through with
one contract of cumulative volume; the same test requiring four contracts
(25% volume sensitivity). Exclude block prints and prints at/before quoting or
at/after expiry. All current/historical pages must succeed across a stable
archive cutoff; malformed identities, missing pages and cursor cycles leave
execution unknown. Neither sensitivity proves queue priority or real fills.
Charge conservative general-quadratic entry and exit fees, rounded up, and
0/1/2-cent exit slippage. Require finalized binary outcomes for paper settlement;
unknown/nonbinary results stay unresolved.

The fixed primary comparison is **depth plus 15-minute expiry plus exit, 25%
volume sensitivity and two-cent exit slippage**, versus baseline hold under the
same volume sensitivity. Other ablations diagnose mechanisms and are not a
menu from which to pick the best historical winner.

## Evidence before any return to funded trading

Evaluate once after enrollment and outstanding outcomes, never by repeatedly
stopping on a favorable P&L. At least 30 independent complete games is a minimum
review condition, not a claim of adequate statistical power. Require all
accounting/economic outcomes known, at least 95% due checkpoint coverage, a
positive lower 95% game-resampled confidence bound for both net returns and
incremental improvement, and positive P&L after removing the best three games.
Require positive primary results in each prespecified calendar half with at
least ten complete games per half. Live cash reconciliation must also pass.
Include zero-fill and abstained opportunities. Report unresolved games separately.
If the period is insufficient, record an inconclusive result; any further study
requires a new version, not extending this one. Any resumption requires a
deliberate owner decision. No research result can enable funded trading.

## NBA and research priorities

Keep the existing equal-size NO/model/fresh-books study unchanged. Refresh
public NBA data and projections, execute that recorder, then produce independent
`nba-model-diagnostics-v1` reports. Report forecast probability buckets and Brier
errors across all resolved opportunities, filled opportunities and unfilled
opportunities. Compare the model with the entry market and fresh two-book
consensus, with coverage explicit and uncertainty grouped by game.

Audit projection/book age, scheduled-tip agreement, injury flags, lineup
confirmation and minutes provenance. A recent projection timestamp does not
make old player information or prior-game minutes a verified forecast for
tonight. Missing lineup confirmation remains unverified. Do not replace it with
an invented status or fit recalibration on the evaluation sample. NFL model
development remains parked; existing paper collectors are left unchanged.

Private reports: `research/spread-paper/latest.json` and
`research/spread-reconciliation/latest.json`. Public NBA diagnostics:
`outputs/nba_model_diagnostics/latest.json`. No private signed evidence is logged
to public Actions or committed to the public repository.
