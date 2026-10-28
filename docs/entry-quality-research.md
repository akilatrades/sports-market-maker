# Entry quality research v1

Approved priority: spread fill quality, then NBA forecast validity. New NFL
model work is parked pending evidence from these two studies. Existing NFL
processes and all funded trading rules, sizes, limits and workers are unchanged.

This protocol is committed before the first prospective observation. It is
separate from [the frozen spread study](spread-forward-study.md). That study's
manifest, start/end dates, implementation and profit-taking simulation remain
unchanged. No new evidence is backdated into it.

## Spread: collect before deciding

`research.spread_entry_recorder` runs once a minute as the existing unprivileged
user. Its only network client is the existing allowlisted GET-only client. It
opens the original observer SQLite database with `mode=ro`. Its own evidence,
manifest, cron entry and release live in `/home/trader/spread-entry-quality`.
It never imports or invokes a funded worker or accesses an order write endpoint.

The new cohort starts on initialization, excludes events already in the original
cohort/baseline, and ends at the existing enrollment end of
2026-11-24 21:47:54.024216 UTC. Settlement follow-up ends December 1 at the same
time. Identity changes require a new study version; a restart never resets dates.

A rotating, outcome-independent sample covers at most 18 eligible/resting
tickers each minute. The candidate universe comes from the original observer's
last 15 minutes of surveys. Signed resting orders before and after each batch
must agree per ticker before subtracting own orders from public depth. Full
fixed-point books and observation times remain in the private SQLite database.
The disk budget is 500 MB; errors are explicit and never converted to zero P&L.

The worker's intent time is the **scan start**, not the exact submission time.
A valid pre-pass book must finish before that timestamp and the book itself
must be at most 120 seconds old. An after-pass snapshot cannot qualify. Report
coverage over all new-cohort accepted orders, including orders without fills.
This sampling study does not promise complete coverage; missing observations
stay unknown and cannot justify a filter. The original 95% checkpoint floor
continues to apply only to the frozen study's due checkpoints.

Frozen diagnostics:

- Full-order external exit depth and an immediate exit gap no larger than 5¢
  per contract, including conservative quadratic entry/exit fee estimates.
- The same screen plus fill time no more than 15 minutes after scan start.
  This is an upper bound on quote age; exceeding it does not prove a stale quote.
- At-fill depth/exit gap comes from the existing verified zero-minute checkpoint.
  Never substitute a later checkpoint for a missing at-fill observation.

These are observed-fill diagnostics, **not executable strategy backtests**.
Changing entries changes queues, capacity, inventory and subsequent orders.
Hypothetical hold-to-settlement P&L uses only verified binary outcomes and actual
entry fees, with unresolved quantity separate. Per-fill depth estimates must
not be summed as if each fill had exclusive access to the same book. Thresholds
are not tuned on this cohort. Before a funded change, require a separate
prospective execution test, adequate independent games and cost sensitivity.

The private exporter adds `research/entry-quality/latest.json`, with hashed
fill/order references, coverage, age/depth diagnostics and game exposure. It
does not publish private evidence to the public repository or workflow logs.
Game exposure sums held and resting cash costs across series with the same
exchange event suffix; unresolved identities stay separate. This is reporting,
not a new live exposure limit or a claim that unlike bets offset one another.

## NBA: equal sizing and equal execution

`research.nba_entry_runner` reads public data only. Existing paper ledgers and
models are untouched. The existing projections workflow runs the new observer
after its usual calculations. Failure of the research step does not block the
existing projection export. A one-time dispatch also produces the historical
audit immediately; stale projections cannot create entries.

The separate manifest pins code identity, initialization time, enrollment end
November 24 and settlement follow-up end December 1 (same UTC times as above).
These dates do not modify the existing spread protocol. All results are paper.

Each eligible opportunity is one NO contract, 2–6 hours before tip, with no
reported injury flag and a projection snapshot at most 30 minutes old. Choose
one line per game/player/stat by quoted midpoint closest to 50%, then ticker;
selection never uses forecast edge. Use a freshly read, two-sided public book,
improve the NO bid by one cent if the spread is at least two cents, otherwise
join. Recheck source age and time to tip after network reads. Preserve source,
book, recent-game, minutes and lineup metadata; `unverified` remains unverified.

Three rules receive the **same opportunity, price, quantity and execution**:

1. Model-free NO baseline: accept the opportunity without a probability veto.
2. Model veto: accept only if model NO probability covers price plus the fee bound.
3. Fresh-books veto: same test using at least two books, updates at most 30 minutes
   old, and exact scheduled-tip agreement. Missing/stale books mean abstention;
   there is no fallback to the model.

The common opportunity pool has a $5 gross cash-and-estimated-fee budget per game
for the whole study. Sort by tip/game/ticker, take the first qualifying observation
of a game/player/stat, and never refill a filtered strategy's unused budget.
This isolates the value of the filter. It does not isolate different stake sizes.

Two fill sensitivities use the same public prints for every rule: strict
trade-through; and touch on an improved quote. Aggregate at least one contract
of qualifying volume, exclude block prints and prices before observation or at/
after tip. Use the exchange's published trade archive cutoff to read all required
current/historical pages, deduplicate and recheck the cutoff; missing
pages, malformed identities or cursor cycles leave execution **unknown**.
Neither assumption establishes actual queue priority. No-fill requires complete
history, not a failed request.

At 1 and 5 minutes after a simulated fill, take the first subsequent public
print within a 60-second allowance, before tip. Report NO-price change from
entry and observation coverage. These are trade-print diagnostics for adverse
selection, not executable exit quotes. Missing prints remain unknown.

P&L requires a finalized/settled binary market result. Charge a conservative
one-contract general quadratic fee with the observed series multiplier, rounded
up to a cent. This is a fee sensitivity bound, not an assertion of actual maker
fees. Report pending/unknown separately, calibration on all resolved opportunities
and on filled subsets, P&L without the best one/three games, and game exposure.
Compare outcomes by independent game, not by treating correlated contracts as
independent trials. Do not declare profitability from this small initial sample.

`historical_audit.json` separately checks existing paper side/price and P&L/fee
arithmetic, timing, forecast win rates and game concentration. Those ledgers lack
freshness timestamps; historical freshness cannot be reconstructed as fact.
The existing `no_seller` already uses a model veto. Existing differently sized
variant profits do not answer whether the probability filter adds value.

## Deployment and repair

`Start isolated entry research` installs only the new observer release and a
hash-guarded private-export hook. It checks the funded production revision,
clean `live/kalshi` source, original manifest and observer file hashes. It never
restarts/arms trading. The existing hourly private exporter publishes new evidence.
The new cron uses a nonblocking lock; overlapping calls cannot duplicate a cycle.
Public logs show health flags only. To stop this research, remove only the cron
line tagged `# spread-entry-readonly-v1` or create its own `STOP` file.

First review recording coverage and identity, then accounting, then calibration
and fee-adjusted outcomes. A broken recorder calls for a recording repair; a
losing or uncertain strategy result calls for more evidence or a new paper
hypothesis. Those are different decisions.
