# NBA opening-week production handoff

Target: **Tuesday, October 20, 2026**. This prepares a bounded production experiment, not a profitability guarantee. Read the [research audit](../docs/NBA_AND_MARKET_AUDIT_2026-10-18.md). Code merged on GitHub is not automatically deployed to the Droplet.

## Tuesday's clock

Confirmed against the [official NBA schedule](https://pr.nba.com/2026-27-nba-regular-season-schedule) and ESPN's production schedule. The worker rechecks the current schedule rather than hardcoding these times.

| Game | Tip, Eastern | Tip, Central | New-entry window, Central |
|---|---:|---:|---:|
| Boston at Detroit | 3:00 p.m. | 2:00 p.m. | 8:00 a.m.–noon |
| Philadelphia at New York | 7:00 p.m. | 6:00 p.m. | noon–4:00 p.m. |
| Oklahoma City at San Antonio | 9:30 p.m. | 8:30 p.m. | 2:30–6:30 p.m. |

Submissions stop 30 seconds before the two-hour boundary. Resting orders expire after at most one hour and before the final two hours. Filled contracts are held to settlement. The timer scans every five minutes; repetitive scans are normal, but completed cycles must print their decisions.

## Owner steps

Run this in the existing **root DigitalOcean console** to update code and stage NBA. The update preserves the previous NFL timer state. Staging does not activate NBA, reset journals or remove KILL files.

```bash
cd /home/trader/sports-market-maker-prod-auto
bash deploy/update_nfl_dashboard.sh
bash deploy/stage_nba_auto.sh
```

After NFL positions have settled and there are no foreign/manual resting orders or open positions, run the handoff **Tuesday morning before 8 a.m. Central**:

```bash
cd /home/trader/sports-market-maker-prod-auto
bash deploy/activate_nba_auto.sh
```

This is an owner-operated activation command. It stops the NFL timer, waits for its current service, then runs signed **production GET-only** checks. It will not sell or cancel an NFL position to make room. If preflight fails, it restores a previously running NFL timer and prints the blockers. If it passes, it arms and starts NBA and selects its journal in the private account dashboard. If activation itself fails after preflight, NFL remains stopped to prevent concurrent trading; inspect the printed error.

If scheduled projections or books have not arrived, wait for the next data update. Do not force arm flags, reset the allowance, remove KILL or disable freshness/roster checks to obtain a trade.

For readiness without activation:

```bash
systemd-run --wait --pipe --collect --uid=trader \
  --property=WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  --property=EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m live.prod_nba_auto --preflight --sync-inputs
```

Preflight while NFL is running should report its isolation blocker. A successful preflight establishes readiness at that moment, not a fill, profit or future feed availability. Fee metadata and the final quote are also checked before each order.

## Execution policy

- Points, rebounds, assists and threes; passive NO entries only. At most one new order per scan and one lifetime submission per ticker. No market orders or automatic exits.
- Current limits (owner-approved fill-measurement sizing for a $250 account, October 21, 2026). Amounts include the 10% reserve:

  | Limit | NBA | Shared with NFL |
  |---|---:|---:|
  | Contracts per order | 2 | — |
  | Cost per order | $4 | — |
  | Orders per game | 10 | — |
  | Per game | $15 | — |
  | Per team, per New York day | $10 | — |
  | Open (active) orders and positions | $75 | $90 |
  | Submitted per New York day | $75 | $105 |
  | Submitted, lifetime | $1,000 | $1,050 |
  | Realized-loss stop, per day | −$20 | — |
  | Realized-loss stop, cumulative | −$60 | — |

  Canceled and unfilled submissions still count toward the daily and lifetime submitted limits. The realized-loss stops are the binding money limit; on a $250 account the cumulative stop is 24% of the balance. In the extreme case that every open order also loses when the stop is reached, the loss could reach about the stop plus the active cap. NFL keeps its own limits ($15 active, $30 daily, $50 lifetime).
- Contract count shrinks until price plus the 10% reserve fits. Reserve is a risk allowance, not an actual expense. Actual reported fees determine P&L.
- Current series/event fees must be understood, estimated net edge must remain positive after the fee bound, and the verified price must stay passive. Unknown fee types block entry.
- Current roster, exact fixture, projection timestamp/checksum and injury news must agree. New team injury news requires refreshed projections; book probabilities predating team news are discarded.
- Long absences over 45 days and transfers require two fresh books on the exact line. Ambiguous player names, unsupported rookies/history, missing context and changed fixtures are skipped.
- Durable intent precedes POST. Uncertain submission stops new orders pending manual reconciliation. Shared process locking and ownership checks prevent the two pilots from independently allocating the same account.

## Data and memory

GitHub Actions downloads history and fits the existing four models. Projections cover today plus two days, so Sunday's source check can see Tuesday. A schema/version, timestamp, row count and SHA-256 bind every CSV to its metadata. Empty off-days publish explicit empty snapshots.

The Droplet downloads only model inputs and the derived book file, pinned to one commit. It does not automatically update executable code, train locally or call the paid book API. Inputs older than nine hours, future-dated inputs or mismatched hashes are rejected. Missing book data clears the cached book file instead of retaining old odds.

Projection schedules: 12:30, 15:30, 18:30 and 21:30 UTC, or 7:30 a.m., 10:30 a.m., 1:30 p.m. and 4:30 p.m. Central on October 20. GitHub jobs can be delayed. The first two runs cover the early game; book collection keeps its existing schedule. Public-source checks never place orders.

Book collection looks only 36 hours ahead. Sunday's successful run had no NBA games in that horizon; the repaired model can already price Tuesday but must not use last season's roles alone. Monday/Tuesday collections must provide at least two fresh books for an opening-week candidate. If they do not, preflight reports `no_verified_projection_rows` and activation stops. That is a specific missing input, not proof that the strategy needs more aggressive prices.

## Monitoring and accounting

```bash
systemctl list-timers market-maker-prod-nba-auto.timer
journalctl -u market-maker-prod-nba-auto.service -n 70 --no-pager
cat /home/trader/prod-nba-auto/last_scan.json
```

`NBA WORKER: completed` confirms completion. `NBA DECISION` and the JSON report distinguish no eligible rows, risk limits, changed quotes, cancellations and accepted orders. Account freshness and worker freshness are separate.

The private dashboard keeps its layout and exchange balances. Handoff selects NBA; NFL journals remain intact. Before switching back, stop/reconcile NBA, change `ACCOUNT_DASHBOARD_MARKET=nfl` in `/etc/systemd/system/market-maker-dashboard.service.d/market.conf`, reload systemd and restart the dashboard. A label change alone does not authorize a trading handoff.

Actual fills are identified by exchange ID and record cost, fees and maker/taker status. Resting orders have repeated queue observations. Actual fills have observed 5/15/60-minute midpoint and executable-bid movements; missing windows are marked missing. Markouts are not realized profit. Settlements normalize dollar costs/fees and cent revenue, using append-only corrections.

The NBA review checkpoint remains 30 days **and** 500 distinct settled buy-fill records with the existing coverage gates. The October 21 limits are sized to reach about 500 fills in two to three weeks of games. No automatic reset or capital increase is implemented. Count independent games as well as fill records.
