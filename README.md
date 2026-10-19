# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

A research and execution system for **passive liquidity provision in Kalshi
sports player-prop markets**. It tests whether retail traders systematically
overpay for "YES" on player props, and whether a patient seller resting "NO"
orders can collect that premium after fees, measured first in historical data
and then with real exchange orders.

**[Live research dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)** ·
**[Research log](RESEARCH_LOG.md)** ·
**[NBA statistical audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)** ·
**[Documentation index](docs/README.md)**

---

## Summary

- **Question.** On Kalshi player props ("Will this player score 25+
  points?"), does the "YES" side trade above its fair probability, as it
  does for long shots in betting markets?
- **Historical finding.** In the 2025–26 NBA season, resting "NO" orders
  one cent inside the ask earned about **+1.7¢ per filled contract with no
  model at all**, and **+2.9¢ when a player-stat model skipped the lines it
  judged fairly priced** (20,641 simulated fills, game-clustered t ≈ 6).
  Taking the model's side at the ask lost money after spread and fees.
- **How much to trust it.** The stricter subsets that use two sportsbooks as
  an independent price check average **+3.4¢ to +4.0¢**, but their 95%
  game-clustered intervals touch or cross zero. Historical fills are inferred
  from public trade prints rather than real queue positions, and some model
  inputs (closing lines) were not available at order time. These results
  justified a small live test; they do not establish an edge.
- **What is built.** Probability models, a sportsbook consensus feed, a
  bounded production order worker with exchange reconciliation, an
  execution-quality monitor, a public dashboard, 300+ tests and a
  chronological research log that records every hypothesis before it was
  run, including the ones that failed.
- **Where it stands.** A capped real-money pilot on NFL props has placed and
  filled real orders. The NBA pilot, the market the research supports, is
  staged for the 2026–27 season behind go/no-go checks and a pre-registered
  evaluation protocol.

## Results

### Historical: 2025–26 NBA player props (simulated fills)

| Rule | Filled contracts | Games | ¢ per contract after fees | 95% interval (game-clustered) |
|---|---:|---:|---:|---|
| Rest "NO" on every line, no model | 33,475 | 1,013 | +1.65 | t ≈ 4.1 |
| Rest "NO" only where the model sees value | 20,641 | 981 | **+2.93** | t ≈ 6.1 |
| Rest "YES" (the opposite side), for contrast | 9,258 | | negative at almost every price | |
| Sportsbook consensus as the filter (sample) | 1,647 | 146 | +3.81 | +0.66 to +6.97 |
| Two books, bounded price and edge, conservative fees | 1,033 | 142 | +3.40 | −0.59 to +7.39 |

Sources: [research log](RESEARCH_LOG.md) and the
[NBA audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md), which recomputes every
row with its input hashes (`python -m research.nba_launch_audit`).

<p align="center">
  <img src="docs/figures/no_vs_yes_by_price.svg" width="720" alt="Profit per contract for resting NO versus resting YES orders by price bucket">
</p>
<p align="center">
  <img src="docs/figures/profit_by_model_edge.svg" width="720" alt="Profit per contract by the model's estimated edge; orders below zero edge are skipped">
</p>

### Live: production pilot (real exchange orders)

| Market | Accepted orders | Filled orders | Contracts | Settled markets | Realized P&L | As of |
|---|---:|---:|---:|---:|---:|---|
| NFL receiving yards | 10 | 4 | 13 | 2 | +$1.99 | 2026-10-19 01:34 UTC |
| NBA player props | Not started | | | | | |

The NFL pilot tests the order, fill, settlement and reconciliation pipeline
with a $50 lifetime budget. It is far too small to say anything about edge.
The live figures on the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
are manually verified snapshots of exchange settlements, not simulations.

## How it works

```
Box scores, schedules, injuries ─► player-stat models ─► P(over the line)
Sportsbook odds (two or more books) ─► de-vigged consensus ─┘
                                                            ▼
Kalshi quotes ─► edge after fees ─► veto / filters ─► risk checks ─► post-only "NO" order
                                                                         ▼
               reconcile with exchange ◄─ settlement ◄─ fill ◄─ queue position
                        ▼
        execution report, forward-validation scorecard, public dashboard
```

- **Models.** For each stat (points, rebounds, assists, threes), a Poisson
  regression on minutes, usage, matchup, betting-line context and teammate
  absences, with an empirical outcome distribution around the mean.
  Validated walk-forward by month on 2021–2026 data. [Model notes](docs/nba-model.md)
- **Sportsbook check.** Odds from multiple books are de-vigged per book and
  averaged, matched to Kalshi by game, player, stat and exact line, and
  rejected when stale at the source.
- **Execution.** Post-only limit orders one tick inside the spread, held to
  settlement. Each run reconciles resting orders, positions and fills against
  the exchange before placing anything, and stops if anything is
  unexplained.
- **Risk.** Hard caps per order, game, team, day and lifetime; injury and
  roster checks that skip or cancel affected markets; a kill switch scoped to
  the strategy's own orders; model-age and data-freshness gates that fail
  closed.
- **Measurement.** Queue position at placement, capture of the volume that
  traded through the order's price, order-level realized P&L, and a
  pre-registered checkpoint (30 days and 500 settled fills) before any
  sizing decision. [Protocol](docs/FORWARD_VALIDATION.md)

## Research process

The research log is the core of the project. The rules it follows:

- **Hypotheses before data.** Every test, threshold and pass criterion is
  written down before the run. Results are appended, never edited into the
  plan.
- **Honest statistics.** Standard errors are clustered by game and by night,
  because props in the same game are correlated (measured intra-game
  correlation +0.03, variance inflation about 1.6×).
- **Multiple-comparison awareness.** A scan of 2,349 testable Kalshi series
  produced 80 nominal passes, about what chance alone would produce; none of
  the seven re-examined candidates survived a family-wise correction.
- **Adversarial review.** Several outside code and methodology reviews are
  recorded in the log, each finding confirmed or rejected against the code.
  Confirmed findings led to fixes (sportsbook snapshot timing, per-game book
  matching, reconciliation before order placement, data-freshness gates);
  none overturned a historical result.

### What did not work, and is recorded as such

| Idea | Result |
|---|---|
| Buying the model's side at the ask | Lost after spread and fees |
| Gradient boosting, hierarchical player effects, isotonic calibration | Better or equal forecasts, no better trading result |
| Game-winner markets on the same rule | Flat to negative across sports |
| Cancelling unfilled orders early, or exiting filled ones early | Gave up most of the profit |
| Ranking orders by fill probability, or by edge per unit of risk | Not robust across halves of the season |
| Cheap "NO" on heavy tennis favorites | Lost; the expensive side carried the result |
| Repeating the study on Polymarket | Not yet possible: almost no player-prop volume |

## Repository

| Path | Contents |
|---|---|
| `markets/nba/`, `markets/nfl/` | Data features and probability models |
| `kalshi/` | Market data, fees, sportsbook consensus, risk limits, signed order client |
| `research/` | Backtests, scans, execution and model studies |
| `live/` | Projections, paper ledgers, the general trader and the bounded production workers |
| `dashboard/` | Public research dashboard (GitHub Pages) |
| `deploy/`, `ops/`, `tools/` | Server setup, owner-run procedures, read-only status checks |
| `tests/` | 300+ unit and end-to-end tests, including adversarial failure cases |
| `outputs/` | Research outputs; live and paper ledgers |

Credentials are never stored in the repository. Production procedures are in
[deploy/](deploy/); activation is a deliberate owner step, never a side
effect of a commit or a test run.

## Running the research

```bash
python -m pip install -r requirements.txt
pytest                                   # offline test suite
python -m research.nba_launch_audit      # recompute the historical audit
python -m live.fetch_nba_data            # refresh box scores
python -m live.nba_projections           # price today's open markets
```

None of these place orders. Network-dependent commands need current market
and sports data and fail closed when it is unavailable.

## Limitations

- One season of NBA prop history; fills are inferred from public prints, not
  from a real queue.
- Some historical model inputs (closing lines, availability from final box
  scores) were more informative than what is known hours before tip-off, so
  the backtest is likely optimistic.
- Live results so far are a small operational pilot. Profitability and
  capacity at scale are unproven.

Research and engineering were done with AI assistance; conclusions are
checked against timestamped market and account data. Nothing here is
investment advice or a claim of future returns.

**License:** MIT. NBA data from sportsdataverse hoopR, NFL data from
nflverse, market data from the venues' public APIs, each under its own terms.
