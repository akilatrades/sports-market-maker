# NBA production worker

The funded NBA bot: `live/prod_nba_auto.py`, strategy version
`nba-no-v4-smaller-orders-edge3-baseline`. It runs on the DigitalOcean
server as a systemd timer, shares one Kalshi account with the NFL bot, and
is a bounded experiment, not a profitability guarantee. Background: the
[research audit](../docs/NBA_AND_MARKET_AUDIT_2026-10-18.md). Code merged on
GitHub reaches the server only through *Deploy funded worker code*.

## Schedule

- **New orders** start 2–6 hours before the scheduled tip-off; the last new
  order goes in 30 seconds before the two-hour mark. The worker reads the
  current schedule each pass rather than hardcoding tip times.
- **Accepted orders rest until the scheduled tip-off**, unless a re-check
  cancels them (edge below 3¢, changed injury news, failed inputs, a stop).
  Filled contracts are held to settlement.
- **Scans** run every 2 minutes from 20:00 to 05:59 UTC (3 p.m. to 1 a.m.
  Central in October) and every 5 minutes otherwise. Repeated scans with
  nothing to do are normal; each completed scan prints its decisions.

## Switching on and off

Use the owner-only **Go live / Stop funded bots** workflow
([GO_LIVE_BUTTON.md](GO_LIVE_BUTTON.md)): `GO_LIVE` arms NBA and NFL
together, `STOP` blocks new orders, `STOP_AND_CANCEL` also cancels the bots'
resting orders. If projections or sportsbook lines have not arrived, wait
for the next data update. Never force arm flags, reset the allowance, remove
a KILL file or turn off freshness or roster checks to get a trade.

The older console scripts (`stage_nba_auto.sh`, `activate_nba_auto.sh`)
were for the single-sport opening-week handoff; `activate_nba_auto.sh` stops
NFL and must not be used while both bots share the account.

Readiness check without trading (DigitalOcean console):

```bash
systemd-run --wait --pipe --collect --uid=trader \
  --property=WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  --property=EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m live.prod_nba_auto --preflight --sync-inputs
```

A passing preflight shows readiness at that moment, not a fill, a profit or
future data availability. Fee metadata and the final quote are checked again
before each order.

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
  | Realized-loss stop, per day | −$20 | −$20 |
  | Realized-loss stop, cumulative | −$60 | −$60 |

  The shared stops count settled NBA and NFL markets together, so losses from either bot stop both. Settlements arrive after games end, so a day's losses mostly block the next day's orders.

  If an input feed (projections, injuries, rosters or quotes) drops out with a connection error, the bot places nothing and holds its resting orders for up to 15 minutes; if good inputs have not returned by then, it cancels them. Data problems (malformed or undated injury records, duplicate tickers, mismatched files) cancel resting orders immediately.

  Canceled and unfilled submissions still count toward the daily and lifetime submitted limits. The realized-loss stops are the binding money limit; on a $250 account the cumulative stop is 24% of the balance. In the extreme case that every open order also loses when the stop is reached, the loss could reach about the stop plus the active cap. NFL keeps its own limits ($15 active, $30 daily, $50 lifetime).
- Contract count shrinks until price plus the 10% reserve fits. Reserve is a risk allowance, not an actual expense. Actual reported fees determine P&L.
- Current series/event fees must be understood and the verified price must stay passive. Estimated edge after the fee bound must be at least 3¢ (and at most 15¢; bigger "edges" are usually data errors) to enter, and at least 3¢ to keep resting. Prices stay within 10–90¢. Unknown fee types block entry.
- Current roster, exact fixture, projection timestamp/checksum and injury news must agree. New team injury news requires refreshed projections; book probabilities predating team news are discarded.
- Long absences over 45 days and transfers require two fresh books on the exact line. Ambiguous player names, unsupported rookies/history, missing context and changed fixtures are skipped.
- Durable intent precedes POST. Uncertain submission stops new orders pending manual reconciliation. Shared process locking and ownership checks prevent the two pilots from independently allocating the same account.

## Data and memory

GitHub Actions downloads history and fits the existing four models. Projections cover today plus two days, so Sunday's source check can see Tuesday. A schema/version, timestamp, row count and SHA-256 bind every CSV to its metadata. Empty off-days publish explicit empty snapshots.

The Droplet downloads only model inputs and the derived book file, pinned to one commit. It does not automatically update executable code, train locally or call the paid book API. Inputs older than nine hours, future-dated inputs or mismatched hashes are rejected. Missing book data clears the cached book file instead of retaining old odds.

Verified inputs are published at 11:30, 12:30, 15:30, 18:30 and 21:30 UTC (*Publish NBA production inputs*); GitHub can start scheduled jobs late, so freshness is checked from the files, not the schedule. Sportsbook lines are collected eight times a day. Public-source checks never place orders.

Book collection looks 36 hours ahead, and a candidate needs at least two fresh books on the exact line. If none qualify, preflight reports `no_verified_projection_rows`; that is a missing input, not a sign that the strategy needs more aggressive prices.

## Monitoring and accounting

```bash
systemctl list-timers market-maker-prod-nba-auto.timer
journalctl -u market-maker-prod-nba-auto.service -n 70 --no-pager
cat /home/trader/prod-nba-auto/last_scan.json
```

`NBA WORKER: completed` confirms completion. `NBA DECISION` and the JSON report distinguish no eligible rows, risk limits, changed quotes, cancellations and accepted orders. Account freshness and worker freshness are separate.

The private account dashboard shows one market's journal at a time, chosen by `ACCOUNT_DASHBOARD_MARKET` in `/etc/systemd/system/market-maker-dashboard.service.d/market.conf` (reload systemd and restart the dashboard after changing it). Changing the label never changes trading.

Actual fills are identified by exchange ID and record cost, fees and maker/taker status. Resting orders have repeated queue observations. For each actual fill, the price movement 5, 15 and 60 minutes later is recorded ("markouts": the midpoint and the price you could actually sell at); missing windows are marked missing. Markouts are not realized profit. Settlements normalize dollar costs/fees and cent revenue, using append-only corrections.

The NBA review checkpoint remains 30 days **and** 500 distinct settled buy-fill records with the existing coverage gates. In the 2025–26 replay (`python -m research.fill_sizing_replay`) these limits reach about 480 filled orders over 37 game nights, when the $1,000 lifetime allowance runs out; the bot then stops placing new orders until the owner raises it. Fewer live fills than the replay would mean fewer filled orders by that point. No automatic reset or capital increase is implemented. Count independent games as well as fill records.
