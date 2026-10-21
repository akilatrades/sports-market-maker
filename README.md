# Sports Market Maker

[![Tests](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml/badge.svg)](https://github.com/akilatrades/sports-market-maker/actions/workflows/tests.yml)

A research and execution system for **passive liquidity provision in Kalshi
sports player-prop markets**. It tests whether resting "NO" limit orders earn
the spread on player props because the traders who cross the spread to buy
"YES" are mostly uninformed, while the traders who would hit a resting "YES"
are not. The question is examined first in historical data and then with
real exchange orders.

**[Recruiter project brief](docs/PROJECT_BRIEF.md)** ·
**[Research dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)** ·
**[Research log](RESEARCH_LOG.md)** ·
**[NBA statistical audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)** ·
**[Documentation index](docs/README.md)**

---

## Summary

- **Question.** Can a model built from public data price Kalshi NBA player
  props ("Will this player score 25+ points?") well enough to trade them
  profitably after fees?
- **First answer: not as a taker.** The pre-registered test failed. The model
  carries information the market price lacks, but buying its side at the ask
  lost money after spread and fees.
- **Exploratory finding.** The market price itself is well calibrated, but
  the order flow is one-sided. In the same 2025–26 season, resting "NO"
  orders one cent inside the ask made **+1.65¢ per filled contract with no
  model** (33,475 simulated fills), while resting "YES" orders lost 2.0¢.
  Using the model only to *skip* lines it judged unfavourable raised the
  result to **+2.93¢** (20,641 fills). Both figures are in-sample: the rule
  was chosen on the same season it is measured on.
- **How much to trust it.** Stricter subsets that use two sportsbooks as an
  independent price check average **+3.4¢ to +4.0¢**, with 95% game-clustered
  intervals that touch or cross zero. Fills are inferred from public trade
  prints, assuming the order was first in the queue at its price, and some
  model inputs (closing lines) were not available at order time. These
  results justify a small forward test, not a claim of edge.
- **What is built.** Probability models, a sportsbook consensus feed, bounded
  production order workers with exchange reconciliation, an
  execution-quality monitor, a public dashboard, 300+ tests and a research log
  that keeps pre-registered tests and exploratory analysis clearly apart.
- **Where it stands (21 October 2026 UTC).** NFL and NBA production
  cohorts have submitted real orders. A signed NBA account audit recorded
  nine accepted orders, one fully filled maker order and one positively
  settled NBA market. This is operational evidence, **not a statistically
  established trading edge**. The current status of production timers
  cannot be inferred from a GitHub commit or a historical dashboard snapshot.

## Results

### Historical: 2025–26 NBA player props (simulated fills, in-sample)

| Rule | Filled contracts | Games | ¢ per contract after fees | 95% interval, game-clustered |
|---|---:|---:|---:|---|
| Rest "NO" on every line, no model | 33,475 | 1,013 | +1.65 | +0.87 to +2.44 |
| Rest "NO" only where the model sees value | 20,641 | 981 | **+2.93** | +1.99 to +3.87 |
| Rest "YES" on every line, for contrast | 9,258 | | −2.03 | t ≈ −3.2 |
| Sportsbook consensus as the filter (151-game sample) | 1,647 | 146 | +3.81 | +0.66 to +6.97 |
| Two books, bounded price and edge, conservative fees | 1,033 | 142 | +3.40 | −0.59 to +7.39 |

The first three rows come from the
[decomposition in the research log](RESEARCH_LOG.md#2026-10-15-where-the-resting-order-profit-comes-from-decomposition-in-sample).
The last two are recomputed with input hashes in the
[NBA audit](docs/NBA_AND_MARKET_AUDIT_2026-10-18.md)
(`python -m research.nba_launch_audit`); in that 151-game sample, all "NO"
fills together average +2.04¢ with an interval of −0.20 to +4.27.

<p align="center">
  <img src="docs/figures/no_vs_yes_by_price.svg" width="720" alt="Profit per contract for resting NO versus resting YES orders by price bucket">
</p>
<p align="center">
  <img src="docs/figures/profit_by_model_edge.svg" width="720" alt="Profit per contract by the model's estimated edge; orders below zero edge are skipped">
</p>

### Live: production pilot (real exchange orders)

| Market | Accepted orders | Filled orders | Contracts filled | Settled markets | Realized P&L | As of |
|---|---:|---:|---:|---:|---:|---|
| NFL receiving yards | 10 | 4† | 13† | 4 | **−$0.69** | 2026-10-19 14:40 UTC |
| NBA player props | 9 | 1 | Not published | 1 | Positive (amount private) | 2026-10-21 04:05 UTC |

The **−$0.69** figure is from an owner-run signed, GET-only production
reconciliation at **14:40 UTC on October 19**: ten accepted NFL orders,
four settled markets, costs and fees matched to private owned order journals.
The earlier **+$1.99** at 01:34 UTC covered two settled markets; the net
realized NFL figure decreased by **$2.68** as two more markets settled.
The owner reports a Matthew Golden loss, but this public aggregate cannot
attribute the whole decrease to that trade. **†Filled-order (4) and
contract (13) counts were last independently reported by the earlier
exchange reconciliation and are not newly established by the 14:40 report.**
The NBA row comes from a **separate signed, private read-only Kalshi
audit on October 21**, which matched one maker fill and one positive
settlement to the strategy's private journal. Exact account amounts and
order-level identifiers are deliberately not published. Nine accepted
orders does **not** imply that eight orders were confirmed unfilled.
[Signed audit evidence](https://github.com/akilatrades/sports-market-maker/actions/runs/39542054076)
and [research interpretation](docs/NBA_OVERNIGHT_AUDIT_2026-10-21.md).
The table mixes **dated, independent snapshots**; it is not a single
live account state or a verified combined portfolio return.

The public [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
checks for a refreshed verified aggregate each minute. It treats reports
over 15 minutes old as **historical**—showing the last verified figure
clearly labelled stale, not as current profit. Automated signed
publication is staged but requires the owner's separate
[Droplet setup](deploy/PUBLIC_PNL_REFRESH.md); publication is
**not yet enabled**. No simulated fill is counted as live P&L.

A new [direct funded-account settled P&L feed](deploy/LIVE_ACCOUNT_PNL.md)
is staged in GitHub. Once an owner-approved HTTPS endpoint is configured,
GitHub Pages will poll actual signed Kalshi account settlements every
15 seconds (Droplet refresh every 30 seconds), without manual GitHub
commits. It will show FUNDED ACCOUNT, NFL and NBA separately. The public
source is **not deployed/connected yet**. Account-wide settlement P&L
is not the same as complete lifetime realized P&L if trades exit early
or move to historical storage.

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
  regression on expected minutes, per-minute rates shrunk toward position
  averages, matchup, betting-line context and teammate absences, with an
  empirical outcome distribution around the mean. Validated walk-forward by
  month on 2021–2026 data. [Model notes](docs/nba-model.md)
- **Sportsbook check.** Odds from multiple books are de-vigged per book and
  averaged, matched to Kalshi by game, player, stat and exact line, and
  rejected when stale at the source.
- **Execution.** Post-only limit orders inside the spread (one tick for NBA;
  the NFL worker may improve by two ticks when the edge allows). Each run
  reconciles resting orders, positions and fills against the exchange before
  placing anything, and stops if anything is unexplained.
- **Risk.** Hard caps per order, game, team, day and lifetime; injury and
  roster checks that skip or cancel affected markets; a kill switch scoped to
  the strategy's own orders; model-age and data-freshness gates that fail
  closed.
- **Measurement.** Queue position at placement, capture of the volume that
  traded through the order's price (the backtest's working assumption is
  50%), order-level realized P&L, and a [forward-validation protocol](docs/FORWARD_VALIDATION.md)
  with a 30-day, 500-settled-fill checkpoint before any sizing decision.

**Current reviewed code policy differs from the historical simulation.**
New NBA orders enter 2–6 hours before verified tip; the current code
**requests** an exchange expiration at scheduled tipoff. The first
verified NBA fill was from an older/unknown strategy generation whose
journal expiration was more than two hours before tip. The new policy
is **not yet independently verified on a newly accepted v4 exchange
order**.
Each resting quote is rechecked against current fees, probabilities,
availability, and the Kalshi book, and can be canceled earlier if invalid.
Late entries 30 minutes–2 hours before tip remain **research only**.
The current small pilot has a $75 lifetime submitted-cost ceiling and a
two-contract-per-order cap, so it cannot by itself satisfy the 500-settled-fill
checkpoint. These controls test execution and reconciliation, not a
demonstrated live trading edge. The earlier one-hour policy remains
historical documentation, not the current source rule.

## Research process

The [research log](RESEARCH_LOG.md) is the core of the project.

- **Pre-registration where it counts.** Confirmatory tests are written down,
  with thresholds and pass criteria, before they are run, and results are
  appended without editing the plan. Exploratory analyses are labelled as
  such, as are choices made after seeing data.
- **Honest statistics.** Standard errors are clustered by game and by night,
  because props in the same game are correlated (measured intra-game
  correlation +0.03, variance inflation about 1.6×).
- **Multiple comparisons.** A scan of 2,349 testable Kalshi series produced
  80 nominal passes out of at least 4,698 comparisons. None of the seven
  candidates re-examined at order level survived a family-wise correction.
- **Adversarial review.** Several outside code and methodology reviews are
  recorded, each finding confirmed or rejected against the code. Confirmed
  findings led to fixes (sportsbook snapshot timing, per-game book matching,
  reconciliation before order placement, data-freshness gates); none
  overturned a historical result.

### What did not work, and is recorded as such

| Idea | Result |
|---|---|
| Buying the model's side at the ask (the pre-registered test) | Lost after spread and fees |
| Gradient-boosted trees for the stat model | Better forecasts (log loss), no better trading result |
| Hierarchical player effects; isotonic calibration | No significant improvement (best: +9.5¢ per 100 orders, t 1.6) |
| Game-winner markets on the same rule | Flat to negative across sports |
| Cancelling unfilled orders after 30–120 minutes | Gave up 40–75% of the profit per order placed |
| Ranking orders by fill probability, or by edge per unit of risk | Not robust across halves of the season |
| Repeating the study on Polymarket | Not yet possible: almost no player-prop volume |

## For hiring teams

Start with the [two-minute project case study](docs/PROJECT_BRIEF.md). It
links each methodological claim to research, execution source code, or
signed exchange evidence, and separates operational successes from
untested profitability claims. This system posts **directional passive-NO
liquidity**; it is not a neutral two-sided market maker.

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

- One season of NBA prop history, and the profitable rule was found in that
  same season. The 2026–27 season is the out-of-sample test.
- Fills are inferred from public prints and assume the order captured every
  contract that traded through its price; real queue position will reduce
  this.
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
