# Spread v3: prospective measurement pilot

Protocol `spread-forward-30d-v1`, fixed before enrollment. This implements the
25 October 2026 research plan. The existing funded entry logic, sizing, limits,
timers and safety handling remain unchanged. The NBA/NFL prop strategies remain
outside this study. This protocol grants no permission to activate or scale any
strategy or to send hypothetical exit orders.

## What starts the clock

The separate unprivileged observer first verifies its account against known
spread order identities, the exact deployed revision and policy, read-only
credentials, existing journals, and one complete scan of all configured series.
Only then does it write an immutable UTC start, end 30 days later, implementation
hash, policy hash and baseline excluded events. Enrollment never restarts after
an outage. A revision/policy mismatch blocks recording and raises a health fault.
Events with any preexisting spread order or position are excluded from the new
cohort. Seven additional days are reserved for settlement follow-up; any still
unresolved outcome remains pending. The bot itself is not stopped at study end.

## Evidence collected automatically

- Signed fill polling targets 15 seconds, with pagination, overlap, persistent
  identities and an hourly full sweep. Actual fees are required; missing is not zero.
- Actual intents, accepted orders, cancellations, fills, worker shadow candidates,
  aggregate rejection reasons and start caches are copied to a private ledger.
- All configured series are surveyed approximately every 10 minutes, including
  unfilled opportunities and rejected candidates. Every observed candidate is
  labeled; event/market/side identifies a unique opportunity. Requotes do not
  create independent samples. These scans have their own observation times:
  **they cannot reconstruct every intrapass capacity/queue decision of the worker.**
  Unobserved worker rejection causes remain unknown, rather than invented.
- Queue positions are sampled during each survey. They do not establish queue
  position at submission or guarantee execution.
- At-fill and 10/30/60-minute checkpoints record full fixed-point books. More
  than 60 seconds late is missing evidence. Two fresh, matching resting-order
  snapshots remove all account-owned depth. A further fill read and signed net
  position check reject inventory races. Series fee metadata and event-start
  tags are preserved. Failed snapshots remain visible in coverage statistics.
- Signed positions and settlements are sampled every five minutes. Binary
  settlement payout is checked against FIFO inventory and signed revenue.
  Scalar, disputed, conflicting and externally modified markets require review.

## One shadow comparison

Baseline: existing entries held to settlement, with actual opposite-side FIFO
netting and actual entry fees. Comparator: the first of the 10/30/60-minute
checkpoints at which the external bid is at least 10 cents above entry triggers
one hypothetical exit attempt for that fill's remaining quantity. Consume visible
depth once across all lots in a snapshot. A partial fill leaves the rest held;
it is not sold again at another checkpoint. Model a taking exit, conservative
per-level fee rounding with the observed series multiplier, and prespecified
0/1/2-cent adverse slippage sensitivities. No alternative threshold/league/price
filter is optimized on this cohort. Own quotes and already-netted inventory
cannot create an exit.

This is a fixed-entry counterfactual: future entry fills are held equal despite
changed hypothetical inventory. Displayed liquidity is not guaranteed execution,
and the snapshot has no latency guarantee. These limitations prevent a shadow
result from proving a realizable live improvement.

## Review and decision

The 30-day report must include all enrolled opportunities, actual after-fee P&L,
fill incidence, unresolved amounts, missed observations, event concentration,
drawdown/capital usage and event-clustered uncertainty with day-level sensitivity.
Review net dollars per unique eligible opportunity only after reconciling the
candidate population with actual worker evidence. Nonfills are zero only when
verified; unknown and unresolved economics are not zero. The automated interim
report deliberately leaves this primary metric pending. It reports matched
shadow comparisons separately and cannot silently drop missing cases to claim
an edge. Remove the best event and best three events as concentration checks.

Measurement-quality floor: 100% accounting identity for reported economics and
at least 95% prespecified checkpoint coverage. Coverage below the floor, unresolved
ownership, unknown execution costs, or an unreconciled opportunity denominator
means **inconclusive**, even with positive P&L. Missing cases still require bounds;
95% coverage is not permission to ignore the remainder. No early success call,
performance-selected extension, automatic scaling, or automatic strategy change.
Before a confirmatory funded experiment, preselect sample/power requirements
using independent-event variability and a meaningful economic margin.

## Operations and privacy

Code lives in a pinned release under `/home/trader/spread-forward-study`; evidence
is compressed SQLite with WAL/full synchronous writes, private file permissions
and a 2 GB limit. The recorder has only allowlisted production GET routes, refuses
redirects, never executes the credential file, and exposes no place/cancel method.
Its own user-cron entry handles restarts. A lock prevents duplicate processes.
An hourly owner-scoped GitHub workflow reads aggregate health over host-pinned
SSH. Research stops at the disk limit or the follow-up deadline without touching
funded workers. Raw account evidence is never uploaded to the public repository
or public Actions artifacts. Server storage is persistent but is not an offsite
backup; loss of evidence invalidates the affected cohort.

Private outputs: `manifest.json`, `evidence.sqlite3`, `health.json`, `report.json`.
Start/status/stop actions operate only on this recorder. Restarting preserves the
original manifest. Research code changes require a separately versioned cohort,
not silent replacement during evaluation.
