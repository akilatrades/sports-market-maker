# Polymarket US: archived quote replay, not maker-fill backtest

The code in `research/polymarket_us_replay.py` queries the **US exchange** public gateway only. It does not access international Polymarket Gamma/CLOB, place orders or require credentials.

Run `python -m research.polymarket_us_replay`. The CI workflow `polymarket-us-replay.yml` can also execute the research read-only and attach `outputs/polymarket_us_replay/latest.json` to its run.

## What is actually measured

- Bounded pages of *closed* NBA and NFL markets, explicitly typed as player props and strictly matched on market question, player, threshold, date and league.
- At most 20 eligible contracts per league for a **first-stage coverage probe**. This is intentionally not a representative sample. Unreadable/empty markets count as missing, not as losses or zero opportunities.
- Price history sampled in the **6-to-2-hour pregame window** with the published short-window `fidelity=1` interface. The public `longPrice` is a display YES ask; `shortPrice` is a display NO ask. They preserve spread, not executions.
- The first displayed quote with enough spread to **hypothetically place a one-cent-improved resting NO bid** without crossing, followed by binary settlement if that API returns a confirmed outcome.
- A mathematically correct payoff **conditional on every hypothetical order being filled**. It is marked `not_trading_profit`, because maker fill selection can be strongly adverse and historical public price series cannot verify queue priority, fill size or resting volume.

## Critical missing pieces before calling this the same Kalshi strategy

1. **Model veto:** Historical, timestamped NBA/NFL model and sportsbook predictions for **exact same player/stat/line/date** must be generated using only information available before each hypothetical order. The replay deliberately emits `model_tested=false` and `expected_edge=null` without this evidence. Do not use final game results to construct probabilities or compare unlike settlement terms.
2. **Maker fills:** Historical L2/market-by-order updates and qualifying trade prints are necessary to reconstruct queue ahead, partial fills, cancellations and capacity. Quotes alone cannot reproduce the Kalshi trade-through replay or support a robust P&L estimate. External proprietary archives must be independently verified.
3. **Fees:** For the Oct 19, 2026 Polymarket US maker schedule, the lowest volume tier has **zero standard maker rebate** until $10M prior-month maker volume. Set rebate and liquidity incentives to zero by default; do not assume our small bankroll earns either.
4. **Selection bias:** 20 sampled contracts/league and 3 pages of catalog are only a coverage smoke test. A real study needs multiple weeks, enough independent games, accurate settlement rules, and a frozen out-of-sample holdout.
5. **Venue separation:** US contracts are not interchangeable with Polymarket International or with Kalshi. Confirm market-specific sport rules, corrections and game delay/void behavior.

## Required eventual comparison

Compare pregame quote opportunities, verified book depth and actual fill probability, net dollars/settled contract, profit per *posted* order (zero for unfilled), game-clustered confidence intervals, drawdown and eligible exposure. Only compare to Kalshi on equivalent game/line/rule subsets and similar execution assumptions.

**Never rank Polymarket ahead of Kalshi using an all-filled hypothetical payoff.** No actual profit has been observed by this script.

Sources: [Polymarket US price-history spec](https://docs.polymarket.us/api-reference/price-history/get-price-history), [markets spec](https://docs.polymarket.us/api-reference/markets/get-markets), [fee schedule](https://docs.polymarket.us/fees).
