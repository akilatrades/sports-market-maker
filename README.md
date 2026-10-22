# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

A research and trading system for **Kalshi sports markets**. It tests two
strategies that only ever rest orders on the book (maker orders, never
taking liquidity):

1. **Prop NO maker.** Resting **NO** limit orders on player props ("Will this
   player score 25+ points?"), priced with statistical models and sportsbook
   odds, because the traders who buy **YES** at the ask are mostly fans.
2. **Spread maker.** A YES bid and a NO bid one cent inside spreads of 8¢ or
   more in 64 smaller series; a filled pair pays $1 for less than $1, and a
   one-sided fill is held to settlement.

Each idea is tested first on historical data, then with real orders under
strict limits.

**[Case study](docs/PROJECT_BRIEF.md)** ·
**[Design decisions](docs/DESIGN_DECISIONS.md)** ·
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
- **A third pattern led to a second strategy.** Across Kalshi's scanned
  series, quoting both sides one cent inside spreads of 5¢ or more made
  **+2.44¢ per contract** (76,694 simulated fills, in-sample), positive in
  both halves of the sample; 67 of 369 series survived a 10%
  false-discovery-rate correction. The spread maker trades 64 of them.
- **Live testing has started.** NFL and NBA bots have traded real money
  under fixed limits since 19–20 October 2026, and the spread maker since
  22 October. A signed NBA account audit on 21 October 2026 recorded
  nine accepted orders, one filled order and one positively settled market.
  This is operational evidence, **not a statistically established edge**.
- **What is built.** Stat models, a sportsbook consensus feed, three
  production order workers sharing one account with exchange
  reconciliation and account-wide loss stops, a fill-quality monitor, a
  public dashboard, 500+ tests and a research log that keeps planned tests
  and exploratory work apart.
- **What is unproven.** Whether live fills earn what the backtests say. The
  headline measurement is the **live fill share**: of the contracts that
  traded at our price while an order rested, how many we got (backtests
  assume all of them). Each bot is judged at a checkpoint written down
  before it went live.

## A 10-minute tour

1. **[Case study](docs/PROJECT_BRIEF.md)** (3 minutes): the question, both
   strategies, the evidence by tier and what is still unproven.
2. **[Design decisions](docs/DESIGN_DECISIONS.md)** (3 minutes): seven
   choices, each with its evidence and the alternative it beat.
3. **A plan written before its results** (2 minutes): the
   [spread maker pilot plan](RESEARCH_LOG.md#2026-10-22-spread-maker-pilot-shadow-and-small-live-plan)
   and the
   [sweep it came from](RESEARCH_LOG.md#2026-10-22-strategy-sweep-across-all-scanned-markets-with-profit-factor-results),
   or the [NBA v5 plan](RESEARCH_LOG.md#2026-10-21-nba-rules-v5-more-orders-for-faster-evidence-plan)
   and its checkpoint.
4. **Code** (2 minutes): `desired_quotes` and `book_quote` in
   [`live/prod_spread_auto.py`](live/prod_spread_auto.py) (pricing without
   bidding against itself, inventory caps); `spread_ledger` in
   [`live/shared_account_risk.py`](live/shared_account_risk.py) (P&L from
   fills, used by the loss stops); and
   [`research/live_checkpoint.py`](research/live_checkpoint.py), which
   grades the live bots against their pre-written bars.
5. **[Dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)**
   for the latest verified live P&L of each strategy.

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

### Historical: two-sided quotes in wide spreads (simulated fills, in-sample)

| Rule | Fills | ¢ per contract | Profit factor | Note |
|---|---:|---:|---:|---|
| Both sides one cent inside 5¢+ spreads, all scanned series | 76,694 | +2.44 (event-clustered t 15.9) | 1.22 | Earlier half +3.07, later half +1.70; about 70% of the profit from filled pairs |
| 8¢+ spreads, hold every fill to settlement | | +3.91 | 1.33 | One-sided fills averaged +5.0¢ held |
| 8¢+ spreads, sell one-sided fills back at the market | | +0.22 | 1.03 | The same fills averaged −4.6¢ sold: hedging pays the spread |
| The 64 pilot series, 5 contracts, $60 cap, 25% of the flow | | +6.5 | | Series chosen on this data: expect less live |

From the [strategy sweep](RESEARCH_LOG.md#2026-10-22-strategy-sweep-across-all-scanned-markets-with-profit-factor-results)
and the [sizing amendment](RESEARCH_LOG.md#2026-10-22-spread-maker-pilot-5-contracts-per-order-plan-amendment).
The first row assumes our order was first in line at its price.

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
[review](docs/NBA_OVERNIGHT_AUDIT_2026-10-21.md). The spread maker went
live on 22 October 2026 and has no published results yet; its realized P&L,
counted from its own fills, appears on the dashboard.

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

- **Spread maker.** Every 10 minutes, in markets 4–7 hours from expected
  expiration with spreads of 8¢ or more, it posts post-only YES and NO bids
  one cent inside, priced from the order book with its own orders removed.
  Up to 5 contracts per order, at most 5 held or resting per market side,
  $60 open, and its own −$10 daily and −$40 total loss stops, inside the
  account-wide stops. A shadow ledger scores the same rule from public trade
  prints alongside, so live and simulated fills can be compared on the same
  markets. [Pilot notes](deploy/PROD_SPREAD_AUTO.md)

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
  candidates checked in detail survived a family-wise correction. The
  spread maker trades only series that survived a 10% false-discovery-rate
  correction, and its simulated edge is still treated as biased upward
  because the series were chosen on the same data.
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
- The spread maker's 64 series were picked from the same scan they are
  judged on (about 6–7¢ simulated in those series against 3.9¢ across all
  wide spreads).
- Live results so far are a small pilot. Profitability and capacity are
  unproven.

Research and engineering were done with AI assistance; conclusions are
checked against timestamped market and account data. Nothing here is
investment advice or a claim of future returns.

**License:** MIT. NBA data from sportsdataverse hoopR, NFL data from
nflverse, market data from the venues' public APIs, each under its own terms.
