# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

A research and trading system for **Kalshi player-prop markets** ("Will this
player score 25+ points?"). It prices each contract with statistical models
and sportsbook odds, then tests one strategy: post resting **NO** limit
orders, because the traders who buy **YES** at the ask are mostly
uninformed. The idea is tested first on historical data, then with real
orders under strict limits.

**[Project brief](docs/PROJECT_BRIEF.md)** ·
**[Dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)** ·
**[Research log](RESEARCH_LOG.md)** ·
**[Documentation](docs/README.md)** ·
**[Start here (collaborators)](docs/START_HERE.md)**

---

## In short

- **The first idea failed.** A model built from public data could not make
  money by buying its preferred side at the ask. That pre-registered test
  lost after spread and fees.
- **A second pattern appeared.** Kalshi's prices are well calibrated, but the
  order flow is one-sided. In 2025–26, resting NO orders made **+1.65¢ per
  contract** with no model, and **+2.93¢** when the model was used only to
  skip unfavourable lines. Resting YES orders lost 2.0¢. These are
  in-sample results from simulated fills.
- **Live testing has started.** NFL and NBA bots trade real money under
  fixed limits. A signed NBA account audit on 21 October 2026 recorded
  nine accepted orders, one filled order and one positively settled market.
  This is operational evidence, **not a statistically established edge**.
- **What is built.** Stat models, a sportsbook consensus feed, production
  order workers with exchange reconciliation, a fill-quality monitor, a
  public dashboard, 500+ tests and a research log that keeps planned tests
  and exploratory work apart.
- **What is unproven.** Whether live fills earn what the backtest says. The
  current phase exists to measure that.

## Results

### Historical: 2025–26 NBA player props (simulated fills, in-sample)

| Rule | Filled contracts | Games | ¢ per contract after fees | 95% interval, game-clustered |
|---|---:|---:|---:|---|
| Rest NO on every line, no model | 33,475 | 1,013 | +1.65 | +0.87 to +2.44 |
| Rest NO only where the model sees value | 20,641 | 981 | **+2.93** | +1.99 to +3.87 |
| Rest YES on every line, for contrast | 9,258 | | −2.03 | t ≈ −3.2 |
| Sportsbook consensus as the filter (151-game sample) | 1,647 | 146 | +3.81 | +0.66 to +6.97 |
| Two books, bounded price and edge, conservative fees | 1,033 | 142 | +3.40 | −0.59 to +7.39 |

The first three rows come from the
[decomposition in the research log](RESEARCH_LOG.md#2026-10-15-where-the-resting-order-profit-comes-from-decomposition-in-sample);
the last two from the [NBA audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)
(`python -m research.nba_launch_audit`).

<p align="center">
  <img src="docs/figures/no_vs_yes_by_price.svg" width="720" alt="Profit per contract for resting NO versus resting YES orders by price bucket">
</p>
<p align="center">
  <img src="docs/figures/profit_by_model_edge.svg" width="720" alt="Profit per contract by the model's estimated edge; orders below zero edge are skipped">
</p>

### Live: real exchange orders

| Market | Accepted orders | Filled orders | Contracts filled | Settled markets | Realized P&L | As of |
|---|---:|---:|---:|---:|---:|---|
| NFL receiving yards | 10 | 4* | 13* | 4 | **−$0.69** | 2026-10-19 14:40 UTC |
| NBA player props | 9 | 1 | Not published | 1 | Positive (amount private) | 2026-10-21 04:05 UTC |

Both rows come from signed, read-only reconciliations of the exchange
account against the bots' own order journals. They are separate dated
snapshots, not one combined account return. *NFL filled-order and
contract counts are from the earlier 01:34 UTC reconciliation. Exact
account amounts and order IDs are not published. Live NBA evidence:
[audit run](https://github.com/akilatrades/sports-market-maker/actions/runs/39542054076),
[review](docs/NBA_OVERNIGHT_AUDIT_2026-10-21.md).

The [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
shows the latest verified settled P&L for each market and labels anything
older than 15 minutes as a past result, never as current profit. Simulated
fills are never counted as live P&L.

## How it works

```
Box scores, schedules, injuries ─► player-stat models ─► P(over the line)
Sportsbook odds (two or more books) ─► de-vigged consensus ─┘
                                                            ▼
Kalshi quotes ─► edge after fees ─► filters ─► risk checks ─► post-only NO order
                                                                    ▼
          reconcile with exchange ◄─ settlement ◄─ fill ◄─ queue position
                        ▼
        fill-quality report, forward-validation scorecard, dashboard
```

- **Models.** For points, rebounds, assists and threes: a Poisson regression
  on expected minutes, per-minute rates shrunk toward position averages,
  matchup, betting lines and teammate absences, with an empirical outcome
  distribution around the mean. Validated month by month on 2021–2026 data.
  [Model notes](docs/nba-model.md)
- **Sportsbook check.** Each book's odds are de-vigged (the bookmaker's
  built-in margin removed), then averaged.
  A line counts only when two or more books quote it, it matches Kalshi's
  game, player, stat and line exactly, and it is fresh.
- **Orders.** Post-only NO limit orders (they only rest on the book, never
  trade immediately) one cent inside the spread, placed 2–6 hours before
  tip-off and resting until tip (NFL: 10 minutes to 2 hours before kickoff). Since NBA rules v5
  (21 October), an NBA order is one contract and needs zero to 15¢ of
  estimated edge after fees to be placed and to stay (NFL keeps 3¢). Each run
  reconciles resting orders, positions and fills with the exchange first,
  and stops if anything is unexplained.
- **Risk.** Limits per order, game, team, day and lifetime; daily and
  cumulative loss stops; injury and roster checks that skip or cancel
  affected markets; a kill switch limited to the bots' own orders.
  [Current limits](deploy/PROD_NBA_AUTO.md#execution-policy)
- **Measurement.** Queue position, the share of passing volume each order
  captures, realized P&L per order, and a
  [forward-validation protocol](docs/FORWARD_VALIDATION.md): a review after
  30 days and 500 settled fills, before any further sizing decision.

The live rule that lets orders rest until tip-off is
not yet independently verified on a live order; the first verified NBA fill
came from an earlier rule version.

## Research process

The [research log](RESEARCH_LOG.md) is the core of the project.

- **Plans before results.** Confirmatory tests are written down, with pass
  criteria, before they run. Results are appended without editing the plan.
  Exploratory work is labelled as such.
- **Honest statistics.** Standard errors are clustered by game, because
  props in the same game are correlated (variance inflation about 1.6×).
- **Multiple comparisons.** A scan of 2,349 Kalshi series produced 80
  nominal passes out of about 4,700 comparisons. None of the seven
  candidates checked in detail survived a family-wise correction.
- **Outside review.** Several independent code and method reviews are
  recorded, each finding confirmed or rejected against the code.

### What did not work

| Idea | Result |
|---|---|
| Buying the model's side at the ask (the pre-registered test) | Lost after spread and fees |
| Gradient-boosted trees for the stat model | Better forecasts, no better trading result |
| Hierarchical player effects; isotonic calibration | No significant improvement |
| Recalibrating the model to Kalshi's listed lines | Worse: −22¢ per 100 orders (t −3) |
| A second cent of price improvement | Worse: −17¢ per 100 orders (t −5) |
| Game-winner markets on the same rule | Flat to negative across sports |
| Cancelling unfilled orders after 30–120 minutes | Gave up 40–75% of the profit per order |
| Ranking orders by fill probability or edge per unit of risk | Not robust across halves of the season |
| Repeating the study on Polymarket | Not yet possible: almost no player-prop volume |

## Running it

```bash
python -m pip install -r requirements.txt
pytest                                   # offline test suite
python -m research.nba_launch_audit      # recompute the historical audit
python -m live.fetch_nba_data            # refresh box scores
python -m live.nba_projections           # price today's open markets
```

None of these place orders. Production runs on a separate server; code is
released with an owner-run GitHub workflow, and the bots are switched on or
off with an owner-only [Go live / Stop button](deploy/GO_LIVE_BUTTON.md).
No credentials are stored in this repository.

## Repository map

| Path | Contents |
|---|---|
| `markets/nba/`, `markets/nfl/` | Features and probability models |
| `kalshi/` | Market data, fees, sportsbook consensus, signed order client |
| `research/` | Backtests, market scans, execution and model studies |
| `live/` | Projections, paper ledgers and the production order workers |
| `dashboard/` | Public dashboard (GitHub Pages) |
| `deploy/`, `ops/`, `tools/` | Server setup, owner procedures, read-only checks |
| `tests/` | Unit and end-to-end tests, including failure cases |
| `outputs/` | Research outputs and published snapshots |
| `docs/` | Project brief, model notes, audits and protocols ([index](docs/README.md)) |

## Limitations

- One season of NBA prop history, and the profitable rule was found in that
  same season. The 2026–27 season is the out-of-sample test.
- Historical fills are inferred from public trades and assume the order was
  first in line at its price. Real queue position will reduce fills.
- Some historical inputs (closing lines, final availability) were more
  informative than what is known hours before tip-off, so the backtest is
  likely optimistic.
- Live results so far are a small pilot. Profitability and capacity are
  unproven.

Research and engineering were done with AI assistance; conclusions are
checked against timestamped market and account data. Nothing here is
investment advice or a claim of future returns.

**License:** MIT. NBA data from sportsdataverse hoopR, NFL data from
nflverse, market data from the venues' public APIs, each under its own terms.
