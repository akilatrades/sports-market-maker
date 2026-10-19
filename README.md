# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

**Experimental Kalshi sports-prop trading system.** Research probability
models, place small passive orders where predicted value exceeds price,
and compare modeled edges with **real exchange orders, fills and final
after-fee settlements**. This is a directional passive-NO strategy, not a
continuously hedged two-sided traditional market maker.

**Continue the ongoing project in one chat:** [CURRENT PROJECT STATE /
living handoff](docs/CURRENT_PROJECT_STATE.md) — verified results, deployment
state, NBA blockers and next tasks, updated as new evidence arrives.

**Start here: [Project explanation, production audit and open risks
(October 18/19)](docs/PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md).**

## The goal, in one minute

A sports prop might ask: **Will a basketball player score 25+ points?**
We estimate the outcome probability from historical usage, minutes,
matchup and availability. If a NO contract is cheaper than our estimated
value, we can submit a *post-only limit order*. Someone must trade at that
price before we own anything. Each contract then pays according to
Kalshi's settlement, and actual costs and fees determine profit.

`Estimate -> compare prices -> filter injuries/books -> risk checks ->
rest an order -> exchange fill -> settle -> reconcile actual P&L`

A positive **estimated** edge can still lose money because of model error,
news, queue position, fees or adverse selection. **Making money in a
historical replay is not evidence of repeatable trading income.**

## Evidence / deployment status

*Status is a timestamped snapshot; consult the [living project state]
(docs/CURRENT_PROJECT_STATE.md) for current Monday/Tuesday readiness.
NFL P&L below is grounded in the 2026-10-19 01:34 UTC authenticated
export; more recent server diagnostics and public NBA input updates are
recorded separately. This file is not a live account feed.*

| Component | Status | What is actually established |
|---|---|---|
| NBA historical research | Exploratory, incomplete certainty | 2025–26 replay is encouraging on some NO-maker subsets. Conservative game-clustered intervals for the strict two-book sample **include zero**. Not real fills. |
| NFL production pilot | **Real exchange orders and maker fills confirmed** | 10 accepted orders, 4 filled orders, 13 contracts; **2 settled markets and +$1.99 realized** in the provided snapshot. Two more filled positions were unsettled then. No income conclusion. |
| NBA production pilot | **Staged, not activated; launch gated** | Production projection pair is now published and synced to DigitalOcean (312 markets). Monday's first two-game odds feed has 71 exact two-book model matches; third game and fresh Tuesday quotes remain to be confirmed. Latest signed preflight still blocked by NFL service isolation and previously missing odds; new preflight required before any authorization. |
| Github dry runs and paper accounts | Research only | Recorded dry submissions and synthetic/print-based fills are **not authenticated Kalshi positions or P&L**. |
| Public dashboard | Sanitized snapshot | Only verified NFL/NBA settled P&L is shown as financial performance. No private account balances or simulated ledger profits. NBA unavailable stays blank. |
| Private dashboard | Read-only server code | Authenticated GET-only account view with separate NFL/NBA production P&L; actual deployment is operator-confirmed, not inferred from git. |

**Do not activate NBA solely because a workflow is scheduled or a model
priced open markets.** NBA needs two fresh exact-line sportsbooks when
required, a new validated model bundle, current injuries, a signed
GET-only server preflight, and no conflicting NFL worker or account
exposure. The code does not self-authorize a live rollout.

## What is in this repository?

| Directory | Purpose | Produces real account trades? |
|---|---|---|
| `markets/nba/`, `markets/nfl/` | Team/player data and probability models | No |
| `research/`, `RESEARCH_LOG.md` | Backtests, rule comparisons and historical failures | No |
| `kalshi/` | Market-data, fee, paper and signed order clients | Only when explicitly called by authorized live worker |
| `live/nba_projections.py`, `live/nfl_projections.py` | Dated model predictions | No |
| `live/nba_trade.py` | Research dry-run / configurable general trader | Not the dedicated production pilot |
| **`live/prod_nfl_auto.py`** | Small bounded real-money NFL worker, private journal | **Only if owner-enabled on server** |
| **`live/prod_nba_auto.py`** | Separate bounded NBA worker, with GET-only preflight | **Only if owner-enabled after handoff** |
| `live/account_dashboard.py` | Authenticated **read-only** account reporting | No |
| `dashboard/` | Public research site + localhost-only private UI | No |
| `outputs/` | Mostly historical/paper research outputs; explicitly labeled public `production_pnl.json` is manually verified | No |

### Public versus private numbers

The [public dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
presents the research, methodology and **only approved exchange-confirmed
settled NFL/NBA P&L**. The public P&L is a **timestamped, manually updated
snapshot** at `outputs/dashboard/production_pnl.json`, not an automatic
production API connection. A missing NBA result is **not zero**.

The private account page, served only through `127.0.0.1` and an SSH
tunnel, reads authenticated real production fills, positions and settlement
records every 60 seconds after deployment. Never commit API keys,
complete private journals or raw order IDs to this repository.

## Research finding and limits

Historical 2025–26 Kalshi NBA player-prop simulations showed a potential
advantage in **resting NO orders** while using calibrated NBA or
sportsbook estimates as a veto. The model-pick *taker* strategy lost
after spread and fees. This informed a hypothesis, **not a guaranteed
edge**. Multiple idea searches, conservative fill assumptions, changing
fees and a single market season limit how confidently it can be scaled.

One strict two-book historical subset had approximately **+3.4¢ per
hypothetical filled contract** under conservative fee rounding, with
a game-clustered confidence interval crossing zero. Trade-through prints
were **not order-book queue executions**. See [the NBA audit]
(docs/NBA_AND_MARKET_AUDIT_2026-10-18.md) for denominators, alternative
fee assumptions and negative findings. See [the chronological research log]
(RESEARCH_LOG.md) for original hypotheses and exploratory results.

The old README and its speculative bankroll-growth examples were
archived in [historical project notes]
(docs/ARCHIVED_EARLY_README_2026-10-17.md); they do not describe today's
funded deployment or expected future income.

## Live safeguards

- Separate dedicated-account cohorts for NFL and NBA: one production
  worker at a time, isolated journals and shared account lock.
- Post-only NO orders with current quote verification, game/roster/injury
  and fee guards, duplicate prevention and an expiry before kickoff/tip.
- NBA bounded pilot: **$50 lifetime gross-submission allowance** with
  a 10% reserve, **$3/order, $3/game, $3/team, $15 active, $30/day**,
  at most five contracts/order and one new order/scan.
- Intent is durably recorded before a signed POST; an ambiguous result
  halts new automation until manually reconciled. KILL switch and
  foreign-order/position checks fail closed.
- Actual fills are identified using exchange IDs, quantities, fees and
  maker/taker status. P&L uses final settlement accounting rather than
  paper-ledger predictions.
- **Important NBA policy nuance:** baseline rule accepts any strictly
  positive final estimated net edge; its *optional second maker tick*
  requires at least 3¢ projected edge afterward. Don't confuse the
  second-tick safeguard with a universal 3¢ baseline veto.

These are code-enforced limitations, **not a claim that the latest
version has been deployed or that the strategy wins**.

## Running research and checks (never starts live trading)

```bash
python -m pip install -r requirements.txt
pytest
python -m live.fetch_nba_data
python -m live.nba_projections
python -m live.nba_publish_check
```

The last three commands need supported network access and current
market/sports data and may fail closed if unavailable. `pytest` and the
normal [test workflow](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)
must pass before any deployment; no passing result for the newest HEAD
was verified as part of this snapshot audit.

A credential-free deployment sanity check, once the updated code is staged
on the Droplet, is `python -m tools.production_status`. It prints local
service/input/journal status **without accessing exchange credentials** and
does not verify the actual Kalshi balance or latest fills.

**For read-only production checks and owner-run procedures**, use
[deploy/PROD_NBA_AUTO.md](deploy/PROD_NBA_AUTO.md),
[deploy/PROD_NFL_AUTO.md](deploy/PROD_NFL_AUTO.md) and
[deploy/ACCOUNT_DASHBOARD.md](deploy/ACCOUNT_DASHBOARD.md).
Deployment/activation is **not** a `pytest` or `git pull` side effect.

## What would make this an income business?

Net profits must be positive **across many independent games and actual
exchange fills**, after real fees, missed quotes, book-data subscriptions,
server costs, slippage, loss periods and taxes. The original project
aims to review a cohort after **30 days and 500 settled fill events**,
with coverage and independence checks. The tiny $50 submission pilot
cannot by itself test scale, capacity or an income target.

The next steps are **fix NBA input publishing and fresh odds coverage;
verify server preflight; reconcile every real NFL settlement; collect
NBA executed orders/fills; compare returns per opportunity and per
filled contract; then evaluate scale separately**. No sizing increase,
policy bypass or automatic trading approval follows from a good week.

### Documentation

- [Plain-language architecture, audit, live-fill reconciliation and
  outstanding issues](docs/PROJECT_MAP_AND_PRODUCTION_AUDIT_2026-10-18.md)
- [Full NBA and cross-market statistical audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)
- [Forward-validation protocol](docs/FORWARD_VALIDATION.md)
- [Historical research decisions and all reported failures](RESEARCH_LOG.md)
- [Production account dashboard and manual P&L updates](deploy/ACCOUNT_DASHBOARD.md)

## Use and responsibility

Research, deployment and reporting code were developed with AI
assistance. Conclusions require independent verification against
timestamped original market and account data. Nothing in this
repository is investment advice or an earnings promise.

**License:** MIT. Upstream NBA data from sportsdataverse hoopR, NFL
data from nflverse and market observations from the venues' APIs,
subject to their respective data terms.
