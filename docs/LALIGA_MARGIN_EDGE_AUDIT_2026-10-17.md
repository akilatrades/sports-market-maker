# La Liga NO-margin strategy — research audit (2026-10-17)

**Verdict: INVESTIGATE; NOT VALIDATED / NOT DEMO-READY.**
The observed paper profits can be explained by five favorable match outcomes and optimistic (not exchange-confirmed) fill assumptions. There is a plausible structural hypothesis — opposing overbought large-win margins while collecting a maker spread — but no positive expected value has been established relative to independent prices.

## Scope and inputs

- Primary source: `outputs/paper_markets/orders.csv` and `scorecard.json` at the 2026-10-17 21:22 UTC snapshot.
- Implementation: `kalshi/paper_markets.py`, `kalshi/maker.py`; the series is `KXLALIGASPREAD`.
- Historical match baseline: La Liga completed seasons **2020–21 through 2025–26** from [datasets/football-datasets (football-data-derived)](https://github.com/datasets/football-datasets/tree/main/datasets/la-liga). Six full seasons, **380 matches each** = **2,280** matches. Only full-time goals were used.
- Selected October 2026 results cross-checked with the [Spanish federation's published results](https://rfef.es/es/resultados?competition=33836084&group=33836085).
- Not a prospective out-of-sample backtest, live account return, or prediction of tomorrow's prices.

## What the actual paper order ledger says

| Metric | Observed |
| --- | ---: |
| Hypothetical limit orders | 32 |
| Settled simulated filled **order rows** | 16 |
| Unique traded market tickers with a settled row | 13 |
| Independent football **matches** | **5** |
| Observation days | **2** |
| Total simulated NO contracts settled | 95 |
| Gross premium/capital spent on filled contracts | $75.47 |
| Modeled maker fees | $0.30 |
| Net paper P&L | **+$19.23** |
| Outcome groups with profitable settled fills | 5 of 5 |
| Net P&L excluding best match | **+$9.22** |
| Share of total profit attributable to best match | **52.1%** |

The dashboard's **17.08¢ per contract** is an **equal-order-row mean** of per-contract return, whereas pooled P&L / pooled volume is **$19.23 / 95 = 20.24¢**. They answer different questions, and neither is a forward-trading expectancy estimate.

Settled paper match contributions (not 16 independent events):

| Market match | Settled rows | Net P&L |
| --- | ---: | ---: |
| Deportivo–Levante | 2 | +$1.80 |
| Espanyol–Atlético | 1 | +$2.35 |
| Villarreal–Elche | 4 | +$10.01 |
| Valencia–Athletic | 6 | +$2.81 |
| Betis–Barcelona | 3 | +$2.26 |
| **Total** | **16** | **+$19.23** |

Several tickers were filled in more than one paper order window. This is why 16 settled rows represent only 13 distinct tickers and 5 matches. Treating 16 rows as independent trials greatly overstates evidence.

### Concrete downside stress

The modeled orders bought **24 NO contracts** against Villarreal winning by 2+ or 3+ goals across the Villarreal–Elche match. If **Villarreal had won by 3+ goals** *and the exact same orders had filled*, those 24 contracts would have paid $0 instead of $1, reducing total simulated P&L by **$24.00** to **−$4.77**. This is a settlement-only counterfactual: order books and realized fills would themselves differ after such news.

**Near-miss illustration:** Barcelona beat Betis **5–2**, a three-goal margin. The recorded Barcelona NO positions concern winning by **more than 3.5, 4.5 and 5.5** goals, so they won; another goal for Barcelona would have made the 3.5-line NO contracts lose.

## Six-season La Liga scoreline frequencies (2020–21 through 2025–26)

These are **unconditional** historical results, not predictions for a particular favorite, team, bookmaker line or Kalshi contract.

| A match had a victory by... | Matches | Percent of 2,280 |
| --- | ---: | ---: |
| At least 2 goals | 729 | **31.97%** |
| At least 3 goals | 292 | **12.81%** |
| At least 4 goals | 97 | **4.25%** |

A particular designated team (one side of each match) won by these margins **15.99%, 6.40% and 2.13%** respectively, when averaged across **both** sides of all games. This baseline mixes strong favorites and underdogs; it **must not** be compared naïvely against the YES prices on selected favorites.

### Profitability requires *prices*, not just common winners

A buy-NO order at price `p`, held to settlement, earns `1-p-fee` if the target winning margin is NOT reached and loses `p+fee` if reached. Ignoring fee, it breaks even when the event's actual YES probability is **below `1-p`**. For instance:
- NO **54¢** only has positive expectancy if the corresponding big-win outcome happens **less than ~46%** of the time, before maker fees.
- NO **97¢** requires the outcome to happen **less than ~3%** of the time, before maker fees. One rare loss can erase many tiny wins.

The audit does **not** possess contemporaneous independent **winning-margin** bookmaker probabilities at the exact order timestamps, so **it cannot establish that Kalshi overprices the YES side**. Unconditional league frequencies cannot fill that gap.

## Potential edge and the main alternative explanation

The algorithm is **model-free** for this series: it collects qualifying quotes **4–10 hours** before market expiration, posts NO at the existing NO bid or 1¢ better (where possible), and cancels after a few hours or at 3h before expiration. Orders are sized to about 1% of each series' simulated $500 bankroll with a daily cap. No calibrated football-margin probability or bookmaker comparison is used in selection.

Two plausible reasons this can *appear* profitable:

1. **Maker spread collection / favorite–longshot bias.** Some bettors may pay too much for exciting large-margin wins, and price-improving NO maker bids can capture spread. Academic work documents favorite–longshot effects in some soccer betting markets, but it is **not evidence that these exact Kalshi alternative-win-margin contracts are overpriced**:
   - [Buhagiar, Cortis & Newall, 2018](https://www.sciencedirect.com/science/article/pii/S2214635018300285) (soccer longshot behavior).
   - [Koning & Zijm, 2023](https://link.springer.com/article/10.1007/s10479-022-04722-3) (Spain-specific favorite bias, mixed across methods and markets).
   - [Hegarty & Whelan, 2025](https://ideas.repec.org/a/eee/intfor/v41y2025i2p803-820.html) (Asian handicap market can be more efficient than conventional 1X2 odds).
2. **Outcome luck plus assumed execution.** All five matches happened to fall short of the selected big-margin outcomes. The paper simulator infers *possible* fills from public trade prints and price priority (`kalshi.maker.fills`), not actual Kalshi Demo accepted maker orders with queue positions. Same-price prints and queue competition can make the model optimistic. The 2026-10-17 sample contains no realized losing NO settlement for this series.

Modeled fees follow `maker_fee(p, share=0.25)` plus rounding. Verify the current **specific event series' fee schedule** against [Kalshi's published fee documents](https://kalshi.com/regulatory/fee-schedule) before any Demo or production rollout.

## A research plan with pass/fail gates — fix criteria *before* seeing future results

1. **Preserve this frozen sample as discovery data.** Do not reuse the five matches as out-of-sample proof or tweak the strategy to maximize their return.
2. **Independent fair prices:** derive per-match score difference probabilities using a rolling Poisson / bivariate-Poisson or Dixon–Coles model, and compare to de-vigged *contemporaneous* sportsbook Asian-handicap / exact-margin quotes, when available. Calibrate on **past dates only**; evaluate held-out dates.
3. **OOS observations:** collect **at least 50 independent matches** and preferably **100+** across multiple matchweeks before declaring tentative statistical evidence. Cluster outcomes by match, not by ticker, fill row or contract; bootstrap event-level P&L.
4. **Execution realism:** distinguish resting matched orders from hypothetical volume prints; haircut same-price or unknown-queue fills (including 0%, 25%, 50% capture scenarios); subtract maker fees, timing differences and missed fills.
5. **Tail and correlated risk:** cap total liability on all alternative margins for the same team/match; shock the model with 2-, 3-, 4- and 5-goal wins and report worst single-match and multi-match losses.
6. **Decision:** pursue *separate* small-scale Kalshi Demo execution only if a predeclared held-out strategy remains net positive across independent matches **and** real Demo fill/settlement evidence supports the modeled capture. No automatic promotion on attractive paper P&L.

**Bottom line:** an interesting paper signal, but the current 16/16 winning fill streak corresponds to only five matches. The research is not enough to conclude a persistent Kalshi mispricing or deploy this market with money.
