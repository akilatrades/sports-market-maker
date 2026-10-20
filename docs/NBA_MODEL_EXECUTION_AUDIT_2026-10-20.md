# NBA October 20 execution and lineup audit

**Status: research PR; not deployed or validated profitable.**

## Actual inputs
The frozen 2025–26 NBA points/rebounds/assists/threes models use
historical as-of minutes, prior starts, player usage, opponent tendencies,
teammates out/returning, rest, spread and game total. The added published
fields `historical_minutes_baseline`, `last_game_minutes`,
`recent_start_rate` and `lineup_confirmation_status=unverified` are
transparent historical features, **not current projected minutes or
confirmed starters**. Those real-time feeds are not available from the
current free sources. ESPN injury status, narrative and updated timestamp
do support an explicit coach minutes-limit veto (added), including older
notes that the model didn't incorporate. Routine newly probable injury
updates no longer unnecessarily block an entire team. Newly questionable,
out, doubtful or restricted teammate changes still veto their team.

A sportsbook probability requires at least **two independent books** at
the exact line. With only one book, the worker may use the historical model
only when existing rotation/roster safeguards allow it. Newly transferred
or offseason-inactive players still require two books.

## Execution consistency
New entries accepted any positive net after-fee edge, whereas subsequent
resting scans previously required 3 cents. The staged v4 pilot now requires
3 cents of verified after-fee edge at **both entry and retention**.
The optional extra second tick is disabled; baseline quoting already moves
one tick inside a sufficiently wide spread. No evidence establishes that
paying the second tick improves actual per-order P&L. New orders are capped
at **2 contracts**, down from 8, to gather smaller diversified observations.
The $8 per-team submission allowance resets by New York trading day while
the $12 per-game / $20 NBA active / $75 lifetime / $35 daily and shared
cross-sport caps remain binding. Previously accepted v3 orders are treated
as old versions and drained safely before new v4 entries.

A separate **30-minute to 2-hour shadow** candidate funnel now runs
alongside the existing 2–6h production funnel. It never submits or cancels
real-money orders. Live expiry remains two hours before tip-off.

## Historical replay results

Reproduce with `python -m research.nba_quote_time_comparison`. Based on
34,756 model-vetoed historical NO-maker quote opportunities (1,040 games);
all policies use the SAME denominator, including a quote expired before
placement as zero possible fills.

| Cutoff before tip | Hypothetical public-print fill rate | Cents per eligible order |
|---|---:|---:|
| 2 hours | 39.02% | +1.207 |
| 1 hour | 48.11% | +1.392 |
| 30 minutes | 52.77% | +1.555 |
| Tip-off | 58.59% | +1.776 |

Three-cent historical model veto retains 24,312 quotes; at 2h:
39.80%/+1.379c; at 30m: 52.67%/+1.748c. The fixed calendar split
also favors 30m in Nov-Jan (+1.158c vs +1.021c at 2h) and Feb-Finals
(+1.686c vs +1.268c). All of this is **in-sample simulation**.

**Crucial limitations:** Public trade-through is NOT proof a newly
inserted order at its actual queue position would fill. No as-of
independent confirmed lineup/current minutes feed, 2026 opening rotation,
actual account fills, true contemporary sportsbook-veto replay, 5-minute
cancellation lag, concurrent position limits or authentic settled P&L are
represented. A later cutoff increases stale-news/adverse-selection risk.
Neither an improved model nor a profitable revised live strategy has been
established by selecting among these backtested windows.

## Release gate
Do not trade the late window until a timestamped verified starters and
independently projected minutes source is connected, tested against
as-of historical observations and monitored in shadow. Then validate
actual Kalshi queue capture, order lifetime, price movement and
settlement returns across independent games. Keep signed exchange
reconciliation, risk caps and owner's explicit deployment approval.
Pushing code to GitHub is not a funded-account deployment.


## Follow-up risk controls not changed in this PR
- Fully canceled zero-fill orders should release their active hold only after
  a **fresh authenticated** order/position/fill reconciliation. A cancel
  response alone cannot establish absence of a partial fill. Existing
  conservative release holds remain until this is separately tested.
- Do **not** replace daily and lifetime submitted-cost caps with filled-only
  caps: an accepted order can still fill and count toward aggregate
  exposures; realized loss is delayed to settlement. Add a verified P&L
  circuit breaker **in addition to**, not instead of, trading-rate limits.
- ESPN Day-To-Day is not a confirmed DNP. The official NBA injury report is
  refreshed frequently, but independent minutes forecasts and confirmed
  starting-lineup feeds have not been integrated or demonstrated reliable.
- The prior historical 2-tick quote-placement table has a documented stale
  price-priority issue; do not treat exploratory differences as live causal
  evidence. NFL's 1c experiment requires a **separate** NFL evaluation.
