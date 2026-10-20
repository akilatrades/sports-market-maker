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
resting scans used an unvalidated 3-cent minimum, leading to potential
early cancellations. Resting scans now use the same positive net-edge floor
as entry. One-cent extra maker-price improvement still requires at least
3 cents of remaining estimated edge. No change to per-order/account caps.

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
