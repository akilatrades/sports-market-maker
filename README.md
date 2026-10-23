# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

I built this to answer one question: **can a small automated trader make
money on Kalshi sports markets by only ever resting orders on the book,
after fees and real fills, not just in a backtest?**

**What I built:** in Python, a signed Kalshi trading client, three bots
that share one risk engine (exchange reconciliation, loss stops, kill
switches), stat models and a sportsbook feed, about 800 offline tests, and
a research log where every confirmatory test is written down before it
runs. **Outcome so far:** the live order handling works; profit is not yet
proven.

It runs two strategies, as three bots (NBA, NFL, spread) on one account,
with real money under tight limits:

1. **Prop NO maker.** Resting **NO** orders on player props ("Will this
   player score 25+ points?"). The people buying YES at the ask are mostly
   fans backing a player, so NO tends to be a little underpriced. A stats
   model and sportsbook odds decide which lines to skip.
2. **Spread maker.** A YES bid and a NO bid one cent inside wide spreads
   (8¢ or more) in 64 series, mostly smaller sports and esports, quoted
   only before the event starts. When both fill, the pair pays $1 for less
   than $1; a one-sided fill is held to settlement.

Every number here is labelled **simulated**, **in-sample** or **live**,
and live and simulated results are never added together.

**[Case study](docs/PROJECT_BRIEF.md)** ·
**[Design decisions](docs/DESIGN_DECISIONS.md)** ·
**[Dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)** ·
**[Research log](RESEARCH_LOG.md)** ·
**[All docs](docs/README.md)**

---

## The short version

- **My first idea failed.** A model built from public data could not make
  money buying its favourite side at the ask. That test was written down
  before it ran, and it lost after spread and fees.
- **The order flow was the edge, not the model.** Kalshi's prices are well
  calibrated, but buying is one-sided. In 2025–26 NBA props, resting NO
  orders made **+1.65¢ per contract** with no model at all and **+2.93¢**
  when the model only vetoed bad lines. Resting YES lost 2.0¢. (Simulated
  fills, in-sample.)
- **The same idea, generalised, became a second strategy.** Across
  Kalshi's scanned series, quoting both sides one cent inside 5¢+ spreads
  made **+2.44¢ per contract** over 76,694 simulated fills, positive in
  both halves of the data, and 67 of 369 series still passed after
  correcting for how many series I tested (a 10% false-discovery-rate
  check). The spread maker trades 64 of the series that passed at 8¢+
  spreads. (Simulated, in-sample.)
- **It is live, and small on purpose.** The NBA and NFL bots have traded
  real money since 19–20 October 2026 and the spread maker since 22
  October. A signed NBA account audit on 21 October recorded
  nine accepted orders, one filled order and one positively settled market.
  That proves the plumbing works; it is **not a statistically established
  edge**.
- **What I am measuring now.** Whether live fills earn what the backtests
  say. The headline number is the **live fill share**: of the contracts
  that traded at my price while an order rested, how many I actually got
  (the backtests assume all of them). The NBA and spread bots are each
  judged at a checkpoint I wrote down before they went live.

## How to read this repo

- **Five minutes:** this page down to [Results](#results), then the
  [case study](docs/PROJECT_BRIEF.md).
- **More time, or a quant's or engineer's eye:** the reading paths in the
  [docs index](docs/README.md#pick-your-path).
- **Live numbers:** the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
  (verified settlements only).

A few terms: *de-vigged* odds have the bookmaker's built-in margin removed;
*profit factor* is winning dollars divided by losing dollars; *t* is a
t-statistic, here always computed with games or events as the unit
(*game-* or *event-clustered*), because results within one game move
together.

## Results

### Simulated: 2025–26 NBA player props (in-sample)

| Rule | Filled contracts | Games | ¢ per contract after fees | 95% interval, game-clustered |
|---|---:|---:|---:|---|
| Rest NO on every line, no model | 33,475 | 1,013 | +1.65 | +0.87 to +2.44 |
| Rest NO only where the model sees value | 20,641 | 981 | **+2.93** | +1.99 to +3.87 |
| Rest YES on every line, for contrast | 9,258 | | −2.03 | t ≈ −3.2 |
| Sportsbook consensus as the filter (151-game sample) | 1,647 | 146 | +3.81 | +0.66 to +6.97 |
| Two books, bounded price and edge, conservative fees | 1,033 | 142 | +3.40 | −0.59 to +7.39 |

The first three rows come from the
[decomposition in the research log](RESEARCH_LOG.md#2026-10-15-where-the-resting-order-profit-comes-from-decomposition-in-sample),
the last two from the [NBA audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)
(`python -m research.nba_launch_audit`).

<p align="center">
  <img src="docs/figures/no_vs_yes_by_price.svg" width="720" alt="Profit per contract for resting NO versus resting YES orders by price bucket">
</p>
<p align="center">
  <img src="docs/figures/profit_by_model_edge.svg" width="720" alt="Profit per contract by the model's estimated edge; orders below zero edge are skipped">
</p>

### Simulated: two-sided quotes in wide spreads (in-sample)

| Rule | Fills | ¢ per contract | Profit factor | Note |
|---|---:|---:|---:|---|
| Both sides one cent inside 5¢+ spreads, all scanned series | 76,694 | +2.44 (event-clustered t 15.9) | 1.22 | Earlier half +3.07, later half +1.70; about 70% of the profit from filled pairs |
| 8¢+ spreads, hold every fill to settlement | | +3.91 | 1.33 | One-sided fills averaged +5.0¢ held |
| 8¢+ spreads, sell one-sided fills back at the market | | +0.22 | 1.03 | The same fills averaged −4.6¢ sold: hedging pays the spread |
| The 64 pilot series, all hours (the first live rule) | 11,263 | +8.45 (t 21.5) | | Same series and window |
| The same series, events whose ticker gives the start: quotes resting wholly before it | 2,285 | +9.87 | | Quotes resting during the game made +2.7¢ |

Rows 1–3 come from the
[strategy sweep](RESEARCH_LOG.md#2026-10-22-strategy-sweep-across-all-scanned-markets-with-profit-factor-results),
rows 4–5 from the [pregame split](RESEARCH_LOG.md#2026-10-23-spread-maker-v2-pregame-only-plan-amendment).
All assume my order was first in line at its price, and the 64 series were
chosen on this same data, so expect less live.

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
[review](docs/NBA_OVERNIGHT_AUDIT_2026-10-21.md). The spread maker is not
in this table yet; the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
shows its realized P&L, counted from its own fills, and labels anything
older than 15 minutes as a past result, never as current profit.

## How it works

```
Prop NO maker (NBA, NFL)
  box scores, injuries ─► stat models ─────────┐
  sportsbook odds (2+ books) ─► de-vigged ─────┴─► fair P(over) ─► skip bad lines
  Kalshi book ─► one cent inside ─► post-only NO ─► rests until tip-off

Spread maker (64 series)
  Kalshi book, own orders removed ─► 8¢+ spread? start known and 85+ min away?
  ─► post-only YES and NO, one cent inside ─► pairs lock in the spread,
     singles held to settlement, everything cancelled 20 min before the start

Every pass, every bot
  journal the order before sending ─► reconcile orders, fills, positions with
  the exchange ─► anything unexplained halts all three bots ─► settle ─► report
```

- **Models.** Points, rebounds, assists and threes: a Poisson regression on
  expected minutes, per-minute rates shrunk toward position averages,
  matchup, betting lines and teammate absences, with an empirical outcome
  distribution. Validated month by month on 2021–2026 data.
  [Model notes](docs/nba-model.md)
- **Sportsbook check.** Each book's odds are de-vigged (the bookmaker's
  margin removed) and averaged. A line counts only when two or more books
  quote it, it matches Kalshi's game, player, stat and line exactly, and it
  is fresh.
- **Prop orders.** Post-only NO orders (they rest on the book, never trade
  immediately) one cent inside the spread, 2–6 hours before tip-off, resting
  until tip (NFL: 10 minutes to 2 hours before kickoff). Since NBA rules v5
  (21 October) an NBA order is one contract and needs 0–15¢ of estimated
  edge after fees (NFL keeps 3¢).
- **Spread orders.** Up to 5 contracts per order, at most 5 held or resting
  per market side, $60 open, and the bot's own −$10 daily and −$40 total
  loss stops. Pregame only since 23 October: on its first live night the
  first version quoted a college football game after kickoff, so now a
  quote needs a known start (from the event ticker, or Kalshi's milestones
  where they have matched ticker times). A shadow ledger scores the same
  rule from public trade prints, so live and simulated fills can be
  compared on the same markets. [Pilot notes](deploy/PROD_SPREAD_AUTO.md)
- **Risk.** Per-order, per-game, per-team, daily and lifetime caps; one
  account-wide loss stop (−$20 a day, −$60 total) over all three bots;
  injury and roster checks; a kill switch limited to the bots' own orders.
  [Current limits](docs/START_HERE.md#current-live-limits)
- **Measurement.** Queue position, live fill share, realized P&L per order,
  and checkpoints written before launch:
  `python -m research.live_checkpoint --data <private export>` grades each
  bot against them. [Forward-validation rules](docs/FORWARD_VALIDATION.md)

## How I work

The [research log](RESEARCH_LOG.md) is the core of the project.

- **Plans before results.** A confirmatory test gets its question, method
  and pass/fail bar written down before it runs. Results are appended
  without editing the plan. Everything else is labelled exploratory, and I
  report how many variants I tried.
- **Statistics that respect the data.** Props in the same game move
  together, so standard errors are clustered by game; the spread maker
  clusters by event. Clustering cuts the model-veto t from
  9.7 to 6.1; for the v5 rule's orders the variance is 2.2 times the
  independent figure.
- **Multiple comparisons.** A scan of 2,349 Kalshi series produced 80
  nominal passes out of about 4,700 comparisons, and none of the seven
  candidates I checked in detail survived a family-wise correction. The
  spread maker trades only series that survived a 10% false-discovery-rate
  correction, and I still treat its simulated edge as biased upward,
  because the series were chosen on the same data.
- **Independent review before money moves.** Changes to the live bots get
  a code review from an agent that did not write them, and every finding
  is fixed or answered before release. On the spread maker those reviews
  caught a bot that would have bid against its own quotes, loss stops that
  could not see closed pairs, and a partial fill that could break an
  inventory cap, all before they cost anything.

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
| Copying the NO rule to other sports (forward paper test, small samples) | Mixed: NFL yards −8.9¢, UFC −9.1¢, ITF tennis about 0, Champions League corners +29¢ on 24 fills |
| Hedging one-sided spread fills | Turned +3.9¢ into +0.2¢ |
| Spread quotes timed from Kalshi's expected expiration | Quoted into a live game on the first night; replaced by a start-time rule |

## Running it

```bash
python -m pip install -r requirements.txt
pytest                                    # about 800 offline tests
python -m research.nba_launch_audit       # recompute the historical NBA audit
python -m research.strategy_sweep         # the cross-market strategy sweep
python -m research.spread_pregame_split   # spread backtest by game phase
python -m live.nba_projections            # price today's open NBA markets
```

None of these place orders. Production runs on a separate server; code is
released with an owner-run GitHub workflow, and the bots are switched on
or off with an owner-only [Go live / Stop button](deploy/GO_LIVE_BUTTON.md).
No credentials are stored in this repository.

## Repository map

| Path | Contents |
|---|---|
| `markets/nba/`, `markets/nfl/` | Features and probability models |
| `kalshi/` | Market data, fees, sportsbook consensus, statistics, signed order client |
| `research/` | Backtests, market scans, execution and model studies |
| `live/` | Projections, paper ledgers and the three production order workers |
| `dashboard/` | The public dashboard (GitHub Pages) |
| `deploy/`, `ops/`, `tools/` | Server setup, owner procedures, read-only checks and exports |
| `tests/` | Unit and end-to-end tests, including failure cases |
| `outputs/` | Research outputs and published snapshots (written by scheduled jobs) |
| `docs/` | Case study, design decisions, model notes, audits and records ([index](docs/README.md)) |

## Limitations

- One season of NBA prop history, and the profitable rule was found in that
  same season. The 2026–27 season is the out-of-sample test.
- Historical fills are inferred from public trades and assume my order was
  first in line at its price. Real queue position will reduce fills.
- Some historical inputs (closing lines, final availability) were more
  informative than what is known hours before tip-off, so the NBA backtest
  is likely optimistic.
- The spread maker's 64 series were picked from the same scan they are
  judged on (+8.5¢ simulated in those series against +3.9¢ across all 8¢+
  spreads, both first in line), and the pregame-only rule keeps a smaller
  share of that simulated profit.
- The NBA rule that lets orders rest until tip-off is
  not yet independently verified on a live order; the first verified NBA
  fill came from an earlier rule version.
- Live results so far are a small pilot. Profitability and capacity are
  unproven.

## About

I used AI assistance for research and engineering; I set the questions,
the rules and the risk limits, and every conclusion is checked against
timestamped market and account data. Nothing
here is investment advice or a claim of future returns.

**License:** MIT. NBA data from sportsdataverse hoopR, NFL data from
nflverse, market data from the venues' public APIs, each under its own terms.
