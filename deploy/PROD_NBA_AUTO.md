# NBA production worker

The funded NBA bot: `live/prod_nba_auto.py`, strategy version
`nba-no-v5-one-contract-breadth`. It runs on the DigitalOcean
server as a systemd timer, shares one Kalshi account with the NFL bot, and
is a bounded experiment, not a profitability guarantee. Background: the
[research audit](../docs/NBA_AND_MARKET_AUDIT_2026-10-18.md). Code merged on
GitHub reaches the server only through *Deploy funded worker code*.

## Schedule

- **New orders** start 2–6 hours before the scheduled tip-off; the last new
  order goes in 30 seconds before the two-hour mark. The worker reads the
  current schedule each pass rather than hardcoding tip times.
- **Accepted orders rest until the scheduled tip-off**, unless a re-check
  cancels them (edge below zero, changed injury news, failed inputs, a stop).
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

- Points, rebounds, assists and threes; passive NO entries only. Up to three new orders per scan, each charged to every limit before the next is considered, and one lifetime submission per ticker. No market orders or automatic exits.
- Current limits (v5, owner-approved on October 21, 2026, to collect fills faster on a $250 account; see RESEARCH_LOG.md "NBA rules v5"). Amounts include the 10% reserve:

  | Limit | NBA | Shared with NFL |
  |---|---:|---:|
  | Contracts per order | 1 | — |
  | Cost per order | $4 | — |
  | Orders per game | 40 | — |
  | Per game | $25 | — |
  | Per team, per New York day | $25 | — |
  | New orders per scan | 3 | — |
  | Open (active) orders and positions | $150 | $165 |
  | Submitted per New York day | $150 | $180 |
  | Submitted, lifetime | $2,000 | $2,050 |
  | Realized-loss stop, per day | −$20 | −$20 |
  | Realized-loss stop, cumulative | −$60 | −$60 |

  The shared stops count settled NBA and NFL markets together, so losses from either bot stop both. Settlements arrive after games end, so a day's losses mostly block the next day's orders.

  If an input feed (projections, injuries, rosters or quotes) drops out with a connection error, the bot places nothing and holds its resting orders for up to 15 minutes; if good inputs have not returned by then, it cancels them. Data problems (malformed or undated injury records, duplicate tickers, mismatched files) cancel resting orders immediately.

  Canceled and unfilled submissions still count toward the daily and lifetime submitted limits. The realized-loss stops are the binding money limit; on a $250 account the cumulative stop is 24% of the balance. In the extreme case that every open order also fills and loses when the stop is reached, the loss could reach the stop plus the active cap: about $60 + $150 = $210 (v4: $135). The per-team cap now equals the per-game cap ($25), so one game's orders may all be on one team's players. NFL keeps its own limits ($15 active, $30 daily, $50 lifetime).
- Contract count shrinks until price plus the 10% reserve fits. Reserve is a risk allowance, not an actual expense. Actual reported fees determine P&L.
- Current series/event fees must be understood and the verified price must stay passive. Estimated edge after the fee bound must be zero or more (and at most 15¢; bigger "edges" are usually data errors) to enter and to keep resting; v4 required 3¢. Prices stay within 5–95¢. Unknown fee types block entry.
- Current roster, exact fixture, projection timestamp/checksum and injury news must agree. New team injury news requires refreshed projections; book probabilities predating team news are discarded.
- **Official NBA injury report** (`markets/nba/official_injuries.py`), checked every scan on top of ESPN's feed. The league publishes it every 15 minutes; the worker reads the newest one (at most 60 minutes old) and the one from when the projections were made. Every rule is per game date, so a team's listing for tomorrow (a back-to-back) never affects tonight:
  - a player listed **Out** or **Doubtful** is vetoed; **Questionable** is vetoed and his teammates need two fresh books;
  - a team whose Out/Doubtful/Questionable listings **changed since the projections** has all its props vetoed until the next projection run (resting orders on them are cancelled); a player whose status changed at all is vetoed;
  - a team still **"not yet submitted"** for the game is vetoed; a team that had not filed when the projections were made needs two fresh books on its props if it now lists anyone high-risk;
  - G League two-way assignments never count as a team change. Probable and Available change nothing; the report never removes a veto.
  - It **fails open**: if the report cannot be fetched or read within 20 seconds (a hard limit; downloads run in a background thread), the scan uses the newest report already downloaded (still at most 60 minutes old), or else continues on ESPN's checks alone. `last_scan.json` shows `official_injury_report` with `status` (`ok` or `unavailable`) and the reason. Downloaded reports are kept for two days in the worker's `inputs/official_injury_reports/` folder (a published report never changes). The reader needs no extra packages; if the PDF layout changes (unknown column, team or status, or a team outside its matchup) it reports an error rather than guessing.
  - Each `cancel_intent` journal entry records the veto that caused it (`veto`, e.g. `OFFICIAL_TEAM_INJURY_CHANGE`), so official-report cancels can be counted.
- Long absences over 45 days and transfers require two fresh books on the exact line. Ambiguous player names, unsupported rookies/history, missing context and changed fixtures are skipped.
- Durable intent precedes POST. Uncertain submission stops new orders pending manual reconciliation. Shared process locking and ownership checks prevent the two pilots from independently allocating the same account.

## Keeping each scan short

Each scan must finish inside the server's 4-minute limit (`TimeoutStartSec=240`); a scan stopped between an order's journal entry and its acceptance halts all future orders until reconciled by hand. With many more resting orders in v5, the worker:

- starts no new order after 150 seconds of runtime (`NEW_ORDER_DEADLINE_SECONDS`);
- fetches fee metadata once per series and game in a scan, not twice per order;
- records each resting order's queue position at most every 10 minutes.

`last_scan.json` reports `pass_seconds` and `orders_placed_this_pass`. If `pass_seconds` regularly approaches 150, investigate before the next deploy.

## Deploying v5, and rolling back

- **Deploy when no NBA order is resting.** Check that Kalshi's Orders tab shows no open NBA orders (or that the readiness preflight reports `legacy_prior_version_resting_orders: 0`). That is usually true after the night's last tip-off and until new entries open six hours before the next day's first tip-off, which is earlier on weekends. If prior-version orders are resting, v5 leaves them untouched until they expire and places nothing until then, and those orders get no injury or edge cancels in the meantime.
- **Rolling back to v4** with v5 orders resting would halt the v4 code (it does not recognise v5). Run **Go live / Stop → STOP_AND_CANCEL** first (this stops both bots and cancels both bots' resting orders), then deploy the older commit, then **GO_LIVE**.

## Data and memory

GitHub Actions downloads history and fits the existing four models. Projections cover today plus two days, so Sunday's source check can see Tuesday. A schema/version, timestamp, row count and SHA-256 bind every CSV to its metadata. Empty off-days publish explicit empty snapshots.

The Droplet downloads only model inputs and the derived book file, pinned to one commit. It does not automatically update executable code, train locally or call the paid book API. Inputs older than nine hours, future-dated inputs or mismatched hashes are rejected. Missing book data clears the cached book file instead of retaining old odds.

Verified inputs are published at 11:30, 12:30, 15:30, 18:30 and 21:30 UTC (*Publish NBA production inputs*); GitHub can start scheduled jobs late, so freshness is checked from the files, not the schedule. Sportsbook lines (*book lines*) are collected for the next 36 hours at 08:15, 12:15, 15:15 and 18:15 UTC, and every 20 minutes from 10:05 to 03:45 UTC for games starting within the next 6.5 hours; a 20-minute run with no game that close spends no Odds API credits. Every pass downloads the newest lines from `main`, so a refresh reaches the bot within one pass. Odds older than 2 hours (75 minutes within 2.5 hours of tip-off) block new orders and cancel resting ones, which is why the near-term refresh runs this often. Public-source checks never place orders.

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

For v5 the review checkpoint is when the $2,000 allowance runs out or 1,900 settled fills, whichever comes first, and in any case at 30 days (RESEARCH_LOG.md, "NBA rules v5"). In the 2025–26 replay (`python -m research.fill_sizing_replay`) the v5 limits reach about 1,900 filled orders over about 51 game nights, when the $2,000 lifetime allowance runs out; the bot then stops placing new orders until the owner raises it. (The v4 limits reached about 480 over 37 nights.) Fewer live fills than the replay would mean fewer filled orders by that point. No automatic reset or capital increase is implemented. Count independent games as well as fill records.
