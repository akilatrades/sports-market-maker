# Project map and production-readiness audit — 2026-10-18/19

> **Read this first.** Sports Market Maker is experimental software, **not a
> verified income-producing business**. This audit distinguishes what the
> repository implements from what was actually observed on Kalshi and what
> remains unverified on the DigitalOcean server.
>
> Review basis: repository code and published research as of October 18/19,
> plus one owner-provided **authenticated, sanitized production NFL
> fills/settlements export generated 2026-10-19 01:34:46 UTC**.
> No private Kalshi account or VPS connection was used for this audit.
> GitHub Actions run status, latest deployment SHA, live NBA preflight and
> post-export NFL settlements were not independently observed.
> Static source inspection is **not a full integration test**.

## 1. Plain-English purpose

A Kalshi contract pays $1 per winning contract and $0 per losing contract
(subject to exchange-specific settlement outcomes). The strategy estimates
a player's probability of reaching an NBA/NFL prop line, compares that
estimate with market prices and, if an estimated advantage remains after
costs and safety checks, **rests a post-only order to buy NO**. It is not
a hedged, two-sided traditional market-making book. A NO buyer loses their
purchase cost if YES settles and earns $1 minus price/fees if NO settles.

Example: model believes P(NO)=70%; NO costs 60 cents. Estimated expected
value is 10 cents before fees *and model error*. A model that overstates
P(NO), stale injury news or adverse fill selection can make the actual edge
negative. An accepted order is not a fill; a fill is not a win.

**Five distinct layers:**

1. Historical **research** (`research/`, `markets/`): market/prop models,
   old Kalshi prices and simulated fill rules. No account trades.
2. Forward **paper experiments** (`kalshi/paper_props.py`,
   `outputs/paper_markets/`, `outputs/paper_maker/`): theoretical order
   and print-based fills, often separate $500 ledgers. They are not funded
   accounts; their P&Ls may not be added into live P&L.
3. GitHub production-market **dry-run** (`live/nba_trade.py` and
   `outputs/live/`): real public venue quotes, but a `dry` order in
   these files is **not** exchange accepted and not a verified fill.
4. **Production execution** (`live/prod_nfl_auto.py`,
   `live/prod_nba_auto.py`): independent, signed, bounded real-money
   workers with private order journals, read-only checks, kill switches,
   and separate entry cohorts. **No evidence both run concurrently.**
5. **Dashboards**: public GitHub Pages for reproducible research and an
   approved manually refreshed **settled P&L snapshot**; localhost-only
   private dashboard for authenticated account data. Neither an animated
   UI nor the public paper scan proves current trading.

Flow: historical player data + current schedule/rosters/injuries +
Kalshi markets + **matched sportsbook odds** -> estimated P(YES) -> NO
quote -> risk/pre-POST gates -> exchange accepted order -> waiting queue ->
real fill -> settlement -> after-fee net P&L and reconciliation.

## 2. Evidence ledger: actual production NFL

From the owner-provided verified export at **2026-10-19 01:34:46 UTC**:

| Measure | Observed | Meaning |
|---|---:|---|
| Exchange accepted / attempts | 10 / 10 | All ten intents have receipts in journal |
| Orders with >=1 real fill | 4 / 10 | **40% of submitted orders**, not market-volume capture |
| Actual fill records | 4 | One distinct exchange fill per filled order |
| Actual filled contracts | 13 | Total across four NO maker executions |
| Filled cash cost | $7.69 | Money spent to acquire positions; **not a loss** |
| Actual maker/taker flags | 4 maker, 0 taker | As reported by exchange |
| Reported fill fees | $0.00 | From this snapshot only |
| Markets settled | 2 of four filled | Other two filled positions were unresolved |
| Settled revenue | $7.00 | Four Bowers and three Worthy contracts |
| Cost of those settled positions | $5.01 | 4 × $0.66 + 3 × $0.79 |
| **Settled net result** | **+$1.99** | $7.00 − $5.01 − $0 reported fees |

Filled order details:

| NO contract | Qty × price | Verified? | Settled net |
|---|---|---|---|
| Brock Bowers at 100+ receiving yards | 4 × $0.66 | Maker, settlement observed | +$1.36 |
| Xavier Worthy at 80+ receiving yards | 3 × $0.79 | Maker, settlement observed | +$0.63 |
| Matthew Golden at 60+ receiving yards | 5 × $0.43 | Maker, no settlement yet in export | Unknown |
| Matthew Golden at 70+ receiving yards | 1 × $0.53 | Maker, no settlement yet in export | Unknown |

The initial fill exporter classified 13 matched contracts as **0
verified NO** because current Kalshi V2 fields `outcome_side=no`,
`book_side=ask` disagreed with deprecated `action=sell, side=no`.
The production-order direction, accepted order ID, actual fill ID,
contract quantities and costs do match. Subsequent export/reporting
changes prioritize the canonical direction fields and preserve the
deprecated-field mismatch as a warning. Never replace the originally
received evidence; it is necessary to explain this correction.

**Caveats:** Small, selected and correlated sample. Both Golden lines are
in one game/player. There is no contemporaneous two-book confirmation
for the final Golden entries (`probability_source=model`). The ten orders
span eight games and six are unfilled. The oldest accepted orders
took ~3 minutes from *recorded intent to acceptance*; the newest two
~9 seconds, but these timestamps are not isolated exchange roundtrip
measurements. Extra maker tick was **not** used by the four fills.
The snapshot does not prove any later positions, fills or P&L.

**Public P&L policy:** `outputs/dashboard/production_pnl.json` carries
only a sanitized timestamped +$1.99 NFL settled snapshot and NBA
unavailable. It **does not stream** account results and must be replaced
with a fresh owner-approved verification when new settlements occur.
Other `outputs/dashboard/summary.json` metrics are research snapshots.

## 3. NBA readiness assessment

**Research model: promising enough for a controlled trial, not proven.**
The October 18 research audit priced 312/312 then-open NBA props for three
opening-day games. It verified roster/schedule/injury/fee source paths and
found no near-term nested-line crossing surviving its rules. Historical
trade-through fills are *not* exchange fills; stronger two-book strict
samples have game-clustered uncertainty intervals that include zero.

**Production (signed real-money) launch: NOT VERIFIED READY.**

| Gate | State based on evidence inspected | What proves it |
|---|---|---|
| Historical four-stat model builds | Historical audit success | Reproduce fresh model job |
| Fresh versioned `latest.csv` and `latest_meta.json` on `main` | **NOT PUBLISHED at last repository check** | Successful publishing workflow + GET same SHA |
| Fresh exact-line NBA consensus at >=2 books where required | **ZERO published coverage**, file header only | A dated nonempty `nba_latest.csv` with real event/line matches |
| Live rosters, kickoff/tip, injury changes | Checks implemented, not current runtime verified | Read-only worker diagnostics on launch day |
| Signed production API, balances/positions | Not accessible via GitHub | DigitalOcean `--preflight` |
| No conflicting NFL production timer, service, resting or held positions | **Unverified** | Operator confirms isolation, settled NFL exposure |
| Deployment SHA and recurring worker completion | **Unverified** | `git rev-parse HEAD`, service logs and systemd state |
| First real NBA order and fill | **No verified NBA report** | Signed accepted/fill journal and settlement reconciliation |

A data-only publisher (`.github/workflows/publish-nba-production-inputs.yml`)
was recently committed. GitHub Actions success and published artifact were
**not confirmed** by this audit. A scheduled workflow is not evidence it ran.
The older `nba-launch-check.yml` uploads **CI artifacts**, not the
main-branch inputs needed by the server. The Droplet pins its download to
the same Git commit and rejects checksum, schema, clock or stale data.

The published `outputs/books/nba_latest.csv` currently has **only its
header**. Since Tuesday opening-week player roles are separated from last
season by >45 days, `nba_candidates()` requires **two fresh books** for
those roles. Do not bypass this to force opening-night orders.

**Rules worth understanding:** The current `no_seller_bookline` candidate
rule allows estimated edge >=0 before a final fee bound; the production
worker enforces **positive** fee-bound net edge at submission, not a 3-cent
minimum for *all baseline orders*. The 3-cent requirement in
`execution_quote()` applies to the optional **second-tick** improvement.
That distinction must be made explicit in every description; evaluate
stronger edge thresholds in research before changing the frozen pilot rule.

The production NBA caps are **$50 lifetime submission allowance including
10% reserve**, $3 per order/game/team, $15 active, $30 daily,
five contracts/order, two orders/game and **one new order per 5-minute
scan**. Entry window: **2–6 hours** before confirmed tip; orders expire
within one hour and before the last two hours. The NBA worker is signed
but **not activated by committing code**; manual handoff follows a
GET-only preflight. Run only after confirming the dedicated account has no
incompatible resting orders/positions and the NFL timer/service are stopped.

## 4. Money as a business (the hard economic question)

A good **positive edge per filled contract** does not necessarily generate
meaningful dollars. Expected gross profit is approximately

`filled contracts × (true edge per contract after exchange fees)`

then subtracts server costs, paid data feeds, taxes, losses from model
misspecification and any capital/financing friction. Filling more often
can make things **worse** if the extra trades are the ones smart traders
choose to hit.

For scale, **$5,000/month** at a *hypothetical proven* **3.4 cents net
profit per filled contract** requires ~**147,059 filled contracts each
month**, before infrastructure costs. At 1 cent, the requirement is
500,000. These are **volume requirements, not profitability forecasts**.
Today's $50 lifetime gross submission experiment cannot establish this
capacity or generate income at that level. Even the October 18 strict
two-book historical sample has uncertainty crossing zero after
conservative fees. Do **not** budget household income against a backtest,
the $1.99 realized NFL result, or a presumed scaling curve.

Before raising capital, require chronological forward evidence of:
- Profit **after real settlement and all actual fees**, plus operating cost;
  confidence intervals **clustered by game**, not by multiple prop lines.
- Number of **accepted**, **resting**, **partially filled**, **fully filled**,
  **settled** and **unfilled/expired** orders, by market/rule/cohort.
- Measured opportunity capture, queue depth, quote age, adverse markout,
  unfilled-best opportunities and net dollars **per posted opportunity**.
- Price / role / injury / source verification, exact-line sportsbook quality
  and realistic quote refresh/cancel failures.
- Tail-loss stress, max drawdown, weekly/monthly variance and bankroll
  endurance, across different game days and seasons.
- Out-of-sample validation: existing **30 days AND 500 settled fill
  events** review checkpoint, recognizing this tiny pilot cannot reach it
  without a separately authorized next experiment.

## 5. P0 / P1 / P2 issues and owner actions

### P0 — Must be closed before NBA real-money activation
1. **Publish NBA inputs successfully.** Confirm `latest.csv` and matching
   `latest_meta.json` exist on main and pass checksum/model/time checks.
   Pending until a real GitHub Actions run is observed.
2. **Obtain valid fresh two-book coverage.** `nba_latest.csv` was empty.
   The book collector's scheduled credentials and actual future coverage
   still need validation. Never interpret a header-only file as valid.
3. **Execute the read-only server preflight.** Confirm deployed SHA,
   production credentials for GET, current roster/injury checks, positions,
   affordability, absence of residual NFL exposure, and stopped NFL
   service/timer. Do not run activation merely because the workflow passes.
4. **Freeze baseline economics/edge policy.** Explicitly accept or research
   the NBA baseline `net_edge > 0` versus a proposed 3¢ minimum after
   actual fee bound. Do not silently rename one as the other.
5. **Reconcile private fills and settled costs** from fresh authenticated
   records before celebrating headline returns. Account-level settlement
   rows might include manual fills in the same ticker unless checked.

### P1 — Correctness and measurement
6. **Private dashboard deployment not verified.** GitHub implementation
   does not prove the server is updated; the update script interrupts the
   NFL timer temporarily. After deployment, confirm both NFL and NBA
   cohort rows with authenticated calls; do not expose keys to the public
   page. Public snapshot is manually approved, not auto-refreshed.
7. **NFL current result incomplete.** The authenticated export covers
   only 2 settled of 4 filled orders; refresh after both Golden contracts
   settle and check exchange order/settlement IDs.
8. **Fee and ownership reconciliation.** Compare settled market NO cost
   with *owned* exchange fill price × quantity; flag account-wide net
   positions, missing trade IDs, cost mismatch and previously owned YES
   inventory as unknown rather than reporting false per-strategy profit.
9. **Backtest/live comparability.** Historical paper fill priority, fee
   assumptions, order lifetimes, liquidity and size differ from production
   worker. Maintain a rule-version-specific bridge; do not call the
   21,373 simulated fill rows 21,373 real trades.
10. **Test run status.** Code and targeted tests have been reviewed/added,
    but this audit does not have a running CI transcript for the current
    HEAD. Never assert a passing build until an actual job succeeds.

### P2 — Repository clarity and longer-term research
11. **README was stale and misleading.** Prior text described only dry-run
    trading, said no real-money authorization existed and highlighted
    speculative bankroll replays as though they were business results.
    Archive that historical README; make the current README a plain-language
    map and honest production status.
12. **Output sprawl remains research history.** Keep old simulation output
    and the timestamped research log for reproducibility; do not delete or
    rebrand it as production. Public P&L widgets now load only
    `production_pnl.json` and display missing NBA as unknown.
13. **More market scans do not create edge.** Keep weather, ITF,
    cross-venue and other categories separate until a model, faithful
    contract matching and forward evidence justify a dedicated trial.
14. **Operating costs and long-term capital plan** need an owner-maintained
    ledger separate from Kalshi account cash. Weekly execution summaries
    are useful; automated income forecasts from simulated performance are not.

## 6. Minimal daily operating checklist

1. **Source checks:** published model and sportsbook timestamps, current
   scheduled fixture, roster/injury feeds, fee information.
2. **Account checks (GET-only):** no unknown positions/orders; active
   exchange balance, Kill files, caps and deployed code identity.
3. **Service checks:** timer state, last successful scan, reason for no
   order, fresh matching exchange quotes; report any unknown submission.
4. **After games:** reconcile unique order IDs and exchange fill IDs,
   maker status, count and cost, settlement outcomes and fee totals;
   flag incomplete rows.
5. **Performance review:** game-clustered returns, per-posted-opportunity
   economics, adverse selection, operational failures and operating costs.
   Do not increase account caps in response to a lucky single slate.

A credential-free operator snapshot is available in updated checkouts:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader .venv/bin/python -m tools.production_status
```

If the Droplet has not been updated and reports `No module named
tools.production_status`, do **not** pull/restart live trading merely to
inspect its state. Run the standalone, standard-library-only diagnostic
instead (as root in the existing checkout):

```bash
curl -fsSL https://raw.githubusercontent.com/akilatrades/sports-market-maker/main/tools/production_status.py -o /tmp/production_status.py
sudo -u trader python3 /tmp/production_status.py
```

The script does not read production credentials, call Kalshi, change
orders or alter systemd units.

It shows the deployed git SHA, local timer states, NBA model input
presence/age/checksum, sportsbook file coverage, and counts from local
private journal event types. It does **not** log in to Kalshi, reveal order
identifiers, verify exchange fills, or place orders. Send this output when
requesting a live-server go/no-go review.

Read-only commands on DigitalOcean **after the user has staged NBA**:

```bash
cd /home/trader/sports-market-maker-prod-auto
git rev-parse --short HEAD
systemctl is-active market-maker-prod-nfl-auto.timer || true
systemctl is-active market-maker-prod-nba-auto.timer || true
systemctl show market-maker-prod-nfl-auto.service -p Result -p ExecMainStatus
systemctl show market-maker-prod-nba-auto.service -p Result -p ExecMainStatus
systemctl status market-maker-dashboard.service --no-pager
```

The NBA signed preflight must be invoked with its own protected production
environment file **after** the NFL handoff isolation conditions can be met;
see `deploy/PROD_NBA_AUTO.md`. Do not run the activation script to merely
diagnose readiness. Never paste env files, API keys, raw private journals
or exchange order IDs into a public issue.

## 7. Navigation

- **[Current README](../README.md)** — what this does and current status.
- **[NBA launch instructions](../deploy/PROD_NBA_AUTO.md)** — exactly how
  the read-only preflight, risk caps and owner activation work.
- **[NBA statistical/market audit](NBA_AND_MARKET_AUDIT_2026-10-18.md)**
  — historical sample uncertainty and cross-market research.
- **[Forward validation protocol](FORWARD_VALIDATION.md)** — predefined
  evidence and review gates.
- **[Private dashboard deployment](../deploy/ACCOUNT_DASHBOARD.md)** —
  localhost-only, authenticated account view.
- **[Original research log](../RESEARCH_LOG.md)** — chronological historical
  experiments, including failures and simulation limitations.

### Audit boundary

This is a deep repository and owner-export **snapshot review**. It is not
an assurance that no bugs exist. This reviewer cannot see the user's
private VPS, cannot query their Kalshi account directly, cannot confirm
current GitHub Actions/deployment status, and cannot rerun the full
historical backtest datasets from this connector session. Those explicit
limitations are themselves P0/P1 gates—not reasons to infer success.
