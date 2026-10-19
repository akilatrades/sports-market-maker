# CURRENT PROJECT STATE — Sports Market Maker

> **Tuesday launch operations:** Follow
> [TUESDAY_NBA_GO_NO_GO_2026-10-20.md](TUESDAY_NBA_GO_NO_GO_2026-10-20.md).
> This is an owner-operated bounded real-money launch with explicit
> go/no-go conditions, not automatic activation.

> **Running project status notes, updated as evidence arrives.**
> Updated after code/source review on October 18–19, 2026. Update after a
> deployment, authenticated exchange reconciliation or important decision.
> Separate **observed evidence**, **merged code**, and **unknown live state**.
> The goal is positive net trading income eventually, but profitability,
> scale and dependable income have **not** been demonstrated.

## Monday October 19 — free TLS certificate issued; public feed test outstanding

Owner-provided Caddy journal screenshot confirms that Let's Encrypt
**validated** `157-230-146-86.sslip.io` via HTTP-01 and Caddy logged
`certificate obtained successfully` for that hostname.
Caddy listened on both **:80** and **:443** and the sslip.io A record
resolved to the Droplet's public IPv4. The signed `127.0.0.1:8766/v1/pnl`
GET still returned account and NFL **−$0.69** settled-market results
with NBA awaiting first order.

- The previous TLS internal-error occurred before certificate issuance.
  Do **not** assume that error persists after issuance.
- External end-to-end HTTPS `GET /v1/pnl`, browser CORS, and non-P&L
  routes must still be explicitly checked; an external tool was not
  able to reach the hostname for independent verification.
- GitHub Pages config `dashboard/live-pnl-source.json` was
  subsequently updated on October 19 (commit `d0066e1`) to reference
  the owner-configured HTTPS endpoint `https://157-230-146-86.sslip.io/v1/pnl`.
  **External end-to-end browser confirmation is still outstanding**;
  neither DNS nor outbound HTTPS to this host can be tested in the
  current assistant execution sandbox. On network/CORS failure the
  public UI shows current P&L unavailable instead of stale gains.
  Verify HTTPS from a real browser, correct Access-Control-Allow-Origin,
  and a 404 on the root route.
- User has selected **public, aggregate-only** settlement P&L.
  Port 8765 (private account dashboard) and port 8766 (internal feed)
  must remain unexposed.

## Monday October 19 — read-only P&L service now active on DigitalOcean

Owner-provided DigitalOcean screenshot confirms:
- `market-maker-live-pnl.service` installed and **active**, configured
  to start automatically at boot.
- Signed sanitized GET request to `http://127.0.0.1:8766/v1/pnl`
  succeeded, with `refresh_type=signed_live_account_settlements_30s`.
- **Funded-account settled P&L −$0.69**, **NFL bot −$0.69** across
  four settled markets, and NBA awaiting first settlement.
- `ss` verified port 8766 is bound to **127.0.0.1:8766** only,
  not public `0.0.0.0`. Private dashboard remains on
  `127.0.0.1:8765`. Neither endpoint has been approved for open
  external network exposure.
- Live data is **not yet connected to GitHub Pages**. Still pending
  free `sslip.io` hostname + Caddy HTTPS restriction to `GET /v1/pnl`,
  TLS/firewall verification, and updating
  `dashboard/live-pnl-source.json` after the HTTPS URL is proven.
- Does not represent every early exit, credit, archived settlement or
  unrealized P&L. No trades/risks were changed to deploy this service.

## Monday October 19, 16:44 UTC — funded-account live-feed check passed

Owner's DigitalOcean screenshot confirms a successful **signed, GET-only**
one-shot check of `live.public_pnl_feed --once` after updating the checkout:

- `refresh_type=signed_live_account_settlements_30s`, exit code **0**.
- **FUNDED ACCOUNT** API-visible settled-market P&L: **−$0.69**,
  four settled markets.
- **NFL** reconciled settled P&L: **−$0.69**, four settled
  markets, ten accepted orders.
- **NBA**: awaiting first order, zero accepted orders or settlements.
- Funded-account and NFL subtotals currently agree. No raw
  identifiers, balances, market tickers or credentials were exposed.
- This proves that a one-time signed settlement read and redacted
  aggregation work. **It does not mean the local 30-second feed service
  or public HTTPS proxy has been started**. Next steps: stage the
  localhost-only systemd service; verify `127.0.0.1:8766/v1/pnl`;
  then configure restricted free HTTPS and finally set the public
  dashboard's nonsecret `live-pnl-source.json` URL.
- Strictly settled-market total: early closed cash-outs and archived
  settled markets are outside the current account aggregation.
  No production trading order or risk setting was changed.

## Free public P&L hostname selection — October 19

User chose a **FREE** domain option. Staged
[free sslip.io + Caddy HTTPS instructions](../deploy/FREE_PNL_HTTPS_SSLIP.md)
and a safe, **read-only** DNS/port/service preflight at
`deploy/free_pnl_https_check.sh`. No domain registration or paid TLS
needed. A stable HTTPS hostname is formed dynamically from the current
Droplet public IP. **No DNS, service, firewall, HTTPS configuration or
public live feed has yet been activated on the owner's Droplet.**
First owner step is to run the preflight and share the listener status.
The future endpoint will publicly expose sanitized account P&L, not
the private 8765 account dashboard.

## October 19 — funded account near-live dashboard plumbing (STAGED)

The user wants **realized wins and losses on the FUNDED Kalshi account**
updated automatically on the recruiter-facing GitHub Pages dashboard.
Earlier static GitHub JSON publication was not a live connection.

- Added `live/public_pnl_feed.py`: **GET-only** Kalshi account
  settlements and separate NFL/NBA cohort reconciliation, 30-second
  background polling, localhost-only sanitized `/v1/pnl` JSON.
- Includes account-wide API-visible settlements, even manual trades.
  Explicitly *does not* include all early cash-outs, archived
  settlements or credits; do not call this all-time realized P&L.
- Public dashboard now polls **every 15 seconds** from an opt-in
  `dashboard/live-pnl-source.json` **HTTPS** endpoint, with no Kalshi
  key in the browser. Default config is blank and keeps the existing
  historical fallback (clearly marked stale).
- Staged `deploy/market-maker-live-pnl.service` and
  [secure setup and accounting limitations](../deploy/LIVE_ACCOUNT_PNL.md).
- **NOT YET DEPLOYED OR EXPOSED** to the internet. We need a stable,
  owner-approved HTTPS domain, valid certificate, initial signed
  account-wide read-only reconciliation, and the owner's explicit
  decision to show aggregate account P&L publicly.
- No changes to trading entry, risk caps, NFT/NBA timers,
  Kalshi credentials or manual publisher token. No automatic service
  enablement has occurred.

## October 19, 14:40 UTC — new signed NFL settlement reconciliation

**Source: owner-provided DigitalOcean terminal result** from
`tools.publish_production_pnl` with signed production **GET-only**
Kalshi fills and settlements, matched to separate private NFL and NBA
accepted-order journals. Exit code 0, **no GitHub write** from Droplet.

- NFL **−$0.69 realized after costs and fees** across **4** settled
  markets, **10** exchange-accepted orders, status
  `verified_snapshot`. This supersedes the historic **+$1.99 / 2
  settled markets** at 01:34 UTC (a net decrease of **$2.68**).
- The owner reports a loss on Matthew Golden. The aggregate reconciles
  the NFL cohort, but **does not establish Golden's individual realized
  settlement cost or which other market(s) changed**. Do not attribute
  the full decrease to one player without an itemized signed export.
- NBA: `awaiting_first_order`, **0** accepted orders and **0**
  settled markets; NFL/NBA accounting remains separate, and no NBA
  realized profit is claimed.
- The public sanitized
  [production P&L snapshot](../outputs/dashboard/production_pnl.json)
  has now been committed with the exact 14:40 UTC as-of timestamp
  and **−$0.69**. Neither private balances nor tickers, raw fills,
  personal identifiers or account credentials are published.
- The public page polls JSON every **60 seconds** and labels
  snapshots older than **15 minutes** stale. It shows the last
  verified historical figure in a caption, but will **not** show it
  as fresh/current P&L without a new signed report.
- [Automated publisher](../deploy/PUBLIC_PNL_REFRESH.md) code and
  a ten-minute timer have been staged **but are NOT enabled** on the
  owner's VPS. They require a separate fine-grained publisher token
  and explicit owner deployment. Never use GitHub historical JSON to
  calculate live risk, and don't place orders through the publisher.

**Risk policy and deployment are unchanged**: NFL worker stopped,
NBA activation remains a separate owner action after signed
preflight. A corrected NFL loss is evidence about the small pilot,
not an estimate of the NBA strategy's edge or income capacity.

## October 19 NBA budget and historical edge review

**NEW reproducible research only; no change to production caps:**
[opening-night sizing audit](NBA_OPENING_NIGHT_SIZING_RESEARCH_2026-10-19.md)
and [actual replay output](../outputs/sizing/nba_oct2026_sensitivity.json).

- Replayed historical 4,862 possible-fill NBA NO rows, filtered to
  **1,033** two-book bounded-edge/price rows over **142 games**.
  One hypothetical book-edge-selected row per game and
  nonrecyclable lifetime reserved allowance, 2–6h entry window.
  This is an outcome/fill-selected **historical sensitivity**, not a
  chronological live-equivalent backtest or independent edge proof.
- Capped history across ~20 selected dates: current $50 lifetime/
  $3-game limits hypothetically earned **+$9.37**; keeping those caps
  with $250 account cash generated **identical results**.
- Changing the caps to $75 lifetime/$4.50-game earned **+$12.54**;
  FIVEFOLD $250 lifetime/$15-game earned **+$28.43** under
  idealized capture assumptions. At only 25% public-print capture,
  they generated **+$6.00 base vs +$6.27 fivefold**. Do not interpret
  these sums as forecasts or real exchange returns.
- Game-resampled conditional 5th-percentile loss about **−$10.24
  (base)** versus **−$53.84 (fivefold)**. Bootstrap excludes
  unfilled order opportunities and is not a calibrated risk forecast.
- Current stricter Oct 18 two-book fee-bound mean remains **+3.40¢**
  with 95% *game-clustered* interval **−0.59¢ to +7.39¢**;
  no statistically reliable all-season NBA live edge established.
- For tomorrow's three games at a purely illustrative 60¢ NO entry
  and +3.4¢ true expected edge, current $3/game limit can submit up
  to **4 contracts per game**, approximately **+$0.41 total** if
  all three fill and the assumed edge is real; a fivefold $15/game
  limit fits 22/game (up to **+$2.24 total**) but increases gross
  all-losing contract cost from **$7.20 to $39.60** across three.
- **Decision:** keep the initial $50, $3/game pilot unchanged for
  opening night. Reconcile real NBA fills and multiple independent
  games before considering any increased allowance. Do not use
  optimistic 2025–26 bankroll replay numbers as expected income.

## Monday October 19 — successful read-only NBA preflight

The owner ran the signed GET-only preflight after stopping the NFL
timer. The reported result was `ready=true`, `failures=[]`, with
a successful exit.

- Both the NFL timer and worker were inactive at the check.
- No resting or held markets, no NBA budget reserved.
- `nba-opening-v2` inputs passed: 312 model rows, about 0.9 hours old.
- 312 open market quotes, 172 rows with sportsbook coverage, 69
  currently verified projection rows. Another 241 required stronger
  independent-book corroboration due to season/role changes.
- No game was in the 2–6-hour entry window on Monday.
- No orders were submitted. NBA activation remains a separate decision.

This is a **point-in-time readiness result**, not a fill, profit
estimate or permanent launch clearance. Before Tuesday activation,
refresh model and sportsbook inputs, confirm the account remains
free of other positions and orders, repeat signed GET-only preflight,
verify NFL isolation and deliberately authorize only the unchanged
bounded pilot. Never publish private account values or keys.

See [Tuesday runbook](TUESDAY_NBA_GO_NO_GO_2026-10-20.md).

## Monday NBA readiness progress — 07:49 AM Central

**Source-confirmed, production-market data-only updates:**

- The scheduled NBA sportsbook collector succeeded around **12:47 UTC**
  (07:47 Central), and a separately triggered one-off refresh around
  **12:48 UTC** also succeeded. Both are GitHub public-data workflows,
  **not real-money trades**.
- `outputs/books/nba_latest.csv` now holds **823** exact sportsbook
  player-prop consensus lines across **Boston–Detroit and
  Philadelphia–New York**, including **309** lines with at least two
  contributing books. No Thunder–Spurs book event yet; it approaches
  the Odds API 36-hour lookahead later this morning.
- Joining the fresh book data with the **312** currently published
  Kalshi model rows by **game day + normalized player + stat +
  exact threshold**, **172** lines match at least one book and **71**
  match at least two books (**29** DET/BOS, **42** NY/PHI, **0** SA/OKC).
  This is a **research-only static join**; it does not check venue
  live quote changes, current injuries, final fee bounds, queue
  availability, or the still-closed Tuesday entry windows.
- **39** of those two-book-matched model rows showed positive
  previously saved `edge_no` values. `edge_no` is **model-derived**
  and cannot substitute for the actual book-based `candidate_orders`
  edge, fresh maker executable quotes, or net real-money profitability.
  This is not an approved trade count or earnings prediction.
- Added a one-time GitHub book-collector refresh on workflow changes
  and an extra **14:15 UTC / 09:15 Central** daily backup sportsbook
  checkpoint to support Tuesday entry-window freshness. These consume
  limited Odds API credits; monitor source usage.
- The last authenticated owner screenshot showed **no open resting
  orders or held positions**, but the NFL scheduled timer was still
  active. **NBA remains disabled** and must pass signed GET-only
  preflight *after* a deliberate NFL handoff and current input sync.
  No automatic activation or risk-limit increase authorized.

**Owner's next read-only step today:** re-sync the NBA inputs and run
`live.prod_nba_auto --preflight --sync-inputs` using protected
production credentials. An `NFL production still active` blocker is
expected until handoff; verify book-covered / verified rows, current
rosters/injuries and account access independently. Do not arm NBA while
any failure remains.

## Monday morning, October 19 — signed account isolation result

**Owner-provided DigitalOcean screenshot:** executed the GET-only,
aggregate-only `tools/check_account_isolation.py` successfully
(exit 0; local machine timestamp 2026-10-19 12:36 UTC).

- `status=NO_RESTING_ORDERS_OR_POSITIONS_AT_THIS_INSTANT`.
- **NFL** known accepted orders: **10**, but **no currently open NFL
  positions or resting orders** in this authenticated production read.
- **NBA** known accepted orders: **0**, with no positions or resting orders.
- `other_or_unrecognized={}`: no unrecognized open exposure at the
  instant sampled.
- This **resolves the prior foreign/open-position blocker at the time
  of that diagnostic**, not permanently. The account can change if the
  still-active NFL timer accepts fresh orders or manual account
  activity occurs. A new signed NBA preflight is required at handoff.
- Crucially, **a flat position is not proof of settlement/P&L**.
  Refresh the authenticated NFL fills+settlements to determine all
  outcomes, including the previously unsettled Golden lines.
- The NFL timer was last observed **active**, NBA timer **inactive**.
  Do not run simultaneous production timers on the same account.
  Account isolation is **one of multiple gates**, not approval to arm NBA.

**Repository recheck after the screenshot:** `outputs/books/nba_latest.csv`
has 404 rows, 157 with two or more books, but the 08:45 UTC (03:45
Central) quote snapshot is nearing its **four-hour freshness cutoff**.
31 current model rows match at least two books, all for Boston–Detroit.
The other two games and revised injury/roster context still require
fresh source verification. Model pair at 12:06 UTC contains 312 rows.

**Next step:** await/verify new sportsbook collection, sync fresh
inputs to the staged NBA worker, and run signed GET-only
`--preflight --sync-inputs`. NFL timer isolation must be planned and
rechecked immediately before any owner-approved activation. No trading
activation was performed.

## Monday morning, October 19 — 07:38 AM Central

**New public data verified by repository inspection:**

- `outputs/books/nba_latest.csv` **is no longer empty**: **404**
  observed sportsbook consensus player-prop line rows from the
  2026-10-19 08:45 UTC (3:45 AM Central) collection; **157** rows had
  at least two sportsbook contributors.
- That collection covers **only Boston at Detroit** so far (one
  event). The 312-row NBA model already matches **76** of the
  exact player/stat/threshold lines at one or more books, but only
  **31** match at **two or more books**; the 31 cover Boston/Detroit.
  The missing two games still require fresh market coverage.
- Book freshness cutoff in `kalshi.books.attach_latest` is **four
  hours** using both snapshot and last contributed price update, so
  08:45 UTC lines become ineligible around 12:45 UTC (07:45 AM
  Central). The next sportsbook collection must be independently
  confirmed, then the Droplet re-synced.
- The newer NBA producer successfully published a fresh 312-row
  model bundle at **2026-10-19 12:06 UTC**.
- The last owner-observed Droplet state still had NBA **inactive**,
  NFL timer **active**, and an open account position that NBA marked
  `Foreign open production position: HALT`. No new signed
  account-isolation report has been supplied yet. **Do not activate
  NBA** based on the arrival of odds alone.
- Next safe owner diagnostic: re-sync inputs after a **fresh** book run;
  separately run `tools/check_account_isolation.py` using protected
  GET-only production credentials to classify NFL/NBA/other held
  exposure. No positions should be automatically liquidated.

## Signed NBA production preflight — October 19, 03:22 UTC

Owner ran a signed, **GET-only** NBA preflight with input synchronization.
The exchange/account request succeeded far enough to check live account
positions. Exit code **2** means no trading authorization, not a worker crash.

- NBA input model `nba-opening-v2` approximately **0.33 h** old; **312**
  currently quoted markets, **0 verified candidates**, **0 two-book lines**.
  Every priced row was excluded with
  `SEASON_OR_ROLE_CHANGE_NEEDS_TWO_BOOKS`. **0 in entry window** is also
  expected because this was Sunday evening, not 2–6 h before Tuesday tip.
- Three blockers: `NFL production still active: NBA trading HALTED`,
  `no_verified_projection_rows`, and
  `Foreign open production position: HALT`. The last means a current
  position is **not owned by NBA's empty order journal**, *not* proof it
  is unauthorized; an NFL-owned position would be classified foreign
  to NBA. No current authenticated position ticker/order attribution
  has yet been provided in this conversation.
- The `account.verified=false` result is due to the foreign-position
  risk halt; it does **not** establish that Kalshi credentials are wrong.
  Do not disable safeguards, close positions automatically or activate
  NBA while this is unresolved.
- A GET-only operator diagnostic, `tools/check_account_isolation.py`,
  now reports **aggregate** open position and resting order ownership
  grouped by NFL-journal, NBA-journal, or unknown, without printing
  balances or raw order/market identifiers. Run it with the protected
  `/etc/market-maker-prod-nba-auto.env` environment on the Droplet
  before deciding whether NFL positions need to settle or whether
  unrelated manual trades need a separate account/handoff review.
- The diagnostics, like a preflight, are point-in-time observations; do
  not infer positions automatically close when a game ends.

## DigitalOcean status update — October 19, 03:19 UTC

**Owner-provided terminal verification after the maintenance deployment:**

- **Deployed checkout:** `f31ce87` (now substantially newer than the previously
  observed `49cda56`); updated private dashboard bound to
  `127.0.0.1:8765`. This is the owner-observed deployed code, **not
  necessarily the newest subsequent GitHub commit**.
- **NBA input sync succeeded:** fresh `nba-opening-v2` CSV and SHA-256
  metadata at `/home/trader/prod-nba-auto/inputs/`, **312 rows**,
  approximately **0.27 hours** old, schema/checksum/age valid.
- **NBA sportsbook sync produced 0 rows**, status
  `file_present_not_feed_approval`. This is **not eligible launch
  coverage**. No two-book opening-night confirmation yet.
- **NBA** production service and timer both **inactive**; journal has
  **0 intents, 0 accepted orders, 0 fills, 0 settlements**.
- **NFL** timer remained **active** and worker inactive between scans;
  local journal preserved **10 intents, 10 accepted orders, 4 fill
  events, 2 settlement events, 0 uncertain submissions**.
- These are local server/journal diagnostics, **not a new authenticated
  Kalshi settlement reconciliation**. NFL final profit and all
  unsettled outcomes remain pending an updated signed account export.
- The NBA producer and GitHub publisher are now verified functional.
  Remaining NBA critical gates: sportsbook coverage inside provider's
  36-hour fixture horizon, then a fresh server sync, updated injuries
  and roster verification, NFL shutdown/position isolation during
  owner-approved handoff, and signed **GET-only** preflight.
- Do **not** activate NBA or disable its protective book requirement
  while sportsbook coverage is zero.

## If you are just joining this project

The experiment trades small Kalshi NBA/NFL **NO** sports-prop contracts.
It estimates the chance a player stays under a quoted line, compares the
estimated value to the exchange price (and sportsbook comparisons where
required), rests **post-only maker orders**, observes real fills, and
settles positions. This is passive *directional* NO trading, not true
two-sided hedged market making.

**Do not confuse:**
1. Historical backtest -> simulated opportunity; replay fills are *not* our fills.
2. GitHub dry-run / paper ledgers -> real public quotes, hypothetical orders.
3. Kalshi Demo -> exchange-like testing in a non-funded venue.
4. Kalshi production NFL/NBA -> signed real-money worker and private journal.
5. Public portfolio dashboard -> research **plus only manually approved,
   timestamped, exchange-verified realized P&L**.
6. Private account dashboard -> authenticated GET-only positions, actual fills
   and independent NFL/NBA settlement P&L; must be deployed to DigitalOcean.

## Verified evidence (do not extrapolate)

### NFL, Kalshi production

From an owner-provided authenticated snapshot exported at **2026-10-19
01:34:46 UTC**, independently compared to local NFL journal counters:

- **10/10 attempted orders exchange accepted**, no ambiguous attempts.
- **4 filled maker orders; 13 contracts; $7.69 total purchase cost**.
  6 accepted orders did not fill in that snapshot.
- Two settled NO orders: Brock Bowers 100+ rec yards (4 at 66¢, +$1.36)
  and Xavier Worthy 80+ rec yards (3 at 79¢, +$0.63).
  **Total realized net NFL P&L: +$1.99** from those two settlements only.
- Two filled Matthew Golden NO lines (5 at 43¢ and 1 at 53¢) were still
  unresolved at the authenticated export timestamp. **Do not present their
  outcome or profit as verified until a new exchange reconciliation.**
- Zero fill fees reported on the four maker fill events. V2 canonical
  `outcome_side=no/book_side=ask` and accepted order IDs match; older
  action/side labels conflicted. The exporter and private dashboard were
  corrected and regressions added.
- Production worker systemd diagnostic **at 2026-10-19 02:35 UTC**:
  `Result=success`, `ExecMainStatus=0`, ~9 second successful scan,
  `decision=no_eligible_candidates`. NFL **timer active**, worker
  inactive between scans. This does not confirm it still operates *now*.
- The **earlier** deployed Droplet commit was **49cda56**. The
  October 19 owner-run maintenance deployed **f31ce87** and restored
  the NFL timer. Subsequent GitHub commits may still be ahead of the
  server and require a separate, controlled deployment.

### NBA, opening Tuesday October 20

- Model **priced 312 of 312 then-open props** for three opening-day games
  in a signed-free public producer check. This demonstrates model/data
  coverage, not edge or real execution.
- **Fixed a critical GitHub Actions publishing false-success bug:** the
  workflow formerly compared an *untracked, newly generated* metadata
  file to itself after `git reset --hard`, exited successfully and
  committed nothing. It now checks **committed** `HEAD:` blobs, verifies
  both blobs' presence, checksum and schema before skipping, protects
  against publishing an older dataset, pushes a versioned CSV+metadata
  pair, and checks that both blobs exist on `origin/main`. Added regression
  tests with a disposable real Git repository, including corrupt data.
- **Verified published on GitHub:** `outputs/projections/latest.csv`
  (312 priced rows) and `latest_meta.json` (schema 2,
  `nba-opening-v2`, SHA-256, generated 2026-10-19 02:56 UTC).
  The NBA worker still needs to sync a **fresh** copy and verify injuries
  and venue quotes on the actual launch day (input age cutoff nine hours).
- **Sportsbook coverage is still the open input gate.**
  `outputs/books/nba_latest.csv` had only its header at last check.
  The Odds API scheduled job on 2026-10-19 01:39 UTC was successful:
  87,567 credits reported remaining, NFL rows from eight books,
  **zero NBA events in its next-36-hour horizon at that time**.
  An **early 08:15 UTC** collection checkpoint was added to the
  sportsbook workflow, in addition to the existing daily refreshes.
  Opening games enter that horizon later Monday; rerun/inspect scheduled
  collections then. A successful collection is not proof of two *fresh,
  exact-line, event-matched* sportsbook quotes.
- NBA DigitalOcean diagnostic showed **worker inactive, timer inactive,
  0 intents and fills, missing local projection/book files**. An NBA
  journal exists, but staging status is partial/unknown.
- **Do not activate** until owner deliberately completes deployment,
  isolation from NFL, current signed GET-only `--preflight --sync-inputs`,
  freshness/roster/injury/two-book checks, and confirms there are no
  foreign resting orders, positions or unsettled NFL exposure.
- NBA pilot risk caps remain **$50 cumulative gross reserved
  submissions**, $3/order/game/team, $15 active, $30/day, five
  contracts/order, one new order per scan, passive only. No automatic
  funding increase.
- Important strategy nuance: baseline estimated net edge must be
  **positive**, while the optional aggressive *extra maker tick* needs
  **3¢** after its price improvement. The latter is **not** a universal
  baseline 3¢ rule.

## Engineering / GitHub state

- Main README rewritten to explain **research vs dry-run vs funded**.
  Original optimistic README archived at
  `docs/ARCHIVED_EARLY_README_2026-10-17.md`.
- Full technical, statistical and production audit:
  `docs/PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md`.
- Public dashboard now shows **only verified NFL/NBA settled P&L** as
  financial performance. Latest owner-approved public snapshot:
  `outputs/dashboard/production_pnl.json`, NFL +$1.99 and NBA
  *unknown*, with timestamp. **Not streaming.**
- Private account dashboard has separate cohorts and improved strict
  fill-ownership/cost reconciliation. These changes are merged into
  GitHub; deployed DigitalOcean version has not been verified updated.
- Following the NBA publisher regression, Python 3.11 + 3.12 CI
  passed **298 tests and 89 subtests** on commit `61aa477` (two
  nonfatal warnings). The documentation-only next commit also passed.
  **Always verify CI on the newest HEAD** before deploying to the Droplet.
- `tools/production_status.py` can run read-only without credentials,
  including standalone via `/tmp`. It reports local services/inputs
  and journal counts, **not** signed exchange accounting.
- No change to production trade side/amount, kill switches, or arming
  during recent documentation, publishing and dashboard work.

## Project economics: what is actually required for income

Prove (a) true after-fee probability edge and (b) enough **verified
exchange-filled liquidity** without adverse selection. Measure by
independent game/market and per posted opportunity, not just profitable
fills. Costs include subscription data, Droplet, fees, missed fills,
losses and taxes. Hypothetical historical cents-per-fill and bankroll
replays must never be advertised or budgeted as stable monthly income.

The project is a **research-to-production experiment**, not an
established business. No present evidence supports a $5k/month claim.

## Work queue (strict priority)

| Rank | Item | State / success criterion |
|---|---|---|
| P0 | NBA input publishing | **Fixed and files confirmed on GitHub.** Check scheduled refresh + SHA and freshness on Tuesday |
| P0 | NBA sportsbook coverage | **Pending:** two fresh exact-line game-matched books for eligible Tuesday players; check new job results inside 36h |
| P0 | Latest full CI | Ensure **both** Python versions pass for current HEAD before any deployment |
| P0 | DigitalOcean version | **Pending owner maintenance:** Git SHA update and NBA staging, without NBA activation or resetting NFL |
| P0 | Read-only signed NBA preflight | **Pending:** verify exchange ownership/positions, fresh roster/injuries, fees, quotes, account funds and isolation |
| P1 | NFL final reconciliation | Export refreshed exchange fills+settlements for both Golden positions and all unfilled/expired orders |
| P1 | Fill-vs-replay reality check | Study queue, accepted->filled, maker/taker, markouts, real net settlement by game/cohort |
| P1 | Private dashboard deployment | Confirm separate NFL and NBA authenticated P&L appears after code update |
| P2 | Future research / scale | Only after sample size, liquidity, drawdowns and income economics justify it |

## The next owner/DigitalOcean operation

**Do not run `activate_nba_auto.sh` while any P0 remains.**

At the last confirmed server state, the NFL timer was active and healthy.
The code update *changes real-money NFL worker code*, so verify current
main CI is green before running the owner-maintenance script. It
temporarily stops then restores the previously active NFL timer.

1. Observe GitHub Actions `tests` green for latest main commit.
2. Follow `deploy/PROD_NBA_AUTO.md` to update the server and **stage
   only** NBA without arming it.
3. Run `sudo -u trader .venv/bin/python -m tools.production_status`
   after a successful update, plus the signed NBA **read-only** preflight
   from `deploy/PROD_NBA_AUTO.md` during a safe NFL handoff window.
4. Review the outputs and all P0 gates before *separately deciding*
   whether to run any owner activation.

Do not send keys, environment files, order IDs or raw private journals
to GitHub or this chat. Summaries and sanitized verified fills suffice.

## Continuing this one conversation

Use this file and the audit as durable project memory. No new chat is
needed to work here; when the conversation becomes long, **refer to this
living file rather than reconstructing old answers**. Bring updated
terminal outputs, authenticated sanitized fill reports or CI results
back **to the same conversation**. Every future major change should
update the work queue with its commit, evidence, and outstanding blockers.

Links:
- [Project README](../README.md)
- [Detailed audit](PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md)
- [NBA rollout instructions](../deploy/PROD_NBA_AUTO.md)
- [Private dashboard](../deploy/ACCOUNT_DASHBOARD.md)
- [Production input publisher](../.github/workflows/publish-nba-production-inputs.yml)
- [Official live model inputs](../outputs/projections/latest_meta.json)
- [Latest sportsbook file](../outputs/books/nba_latest.csv)
- [Real settled P&L public snapshot](../outputs/dashboard/production_pnl.json)
