# Cross-exchange prop watch: Kalshi vs Polymarket US

This **research-only** job compares public NBA and NFL player-prop listings. It never authenticates with Polymarket, requires no deposit, and cannot submit or cancel orders. The DigitalOcean Kalshi Demo bot and its limits are unchanged.

## Data sources

- **Polymarket US** public [league events](https://docs.polymarket.us/api-reference/sports/get-events-by-league-slug) and [best bid/offer](https://docs.polymarket.us/api-reference/markets/get-market-bbo) under `https://gateway.polymarket.us`. **Not** the international Gamma/CLOB API on `polymarket.com`.
- **Kalshi production public market data** (`kalshi.api.fetch_markets`) for NBA points, rebounds, assists, threes, NFL receiving yards and anytime touchdown. This is read-only research *against production quotes*, not Kalshi Demo account executions.

## What gets counted

A Polymarket US listing is considered a candidate only when its documented sports market type says `SPORTS_MARKET_TYPE_PROP` and its text identifies an **explicit OVER / at-least outcome**, player, statistic and line. For Kalshi, the match uses its prop series, player, numeric strike and event date.

The two keys must match exactly on **league, Eastern game date, normalized player name, stat and threshold**. Ambiguous or missing information is excluded rather than guessed. Every candidate still needs human comparison of contract language, corrections, postponement, ties and settlement procedures before any return/arbitrage claim.

If the candidate is unique on both sides, the tool queries public Polymarket US BBO and compares both exchange's YES bid/ask quotes. It reports **midprice differences for research only**; it never calculates a fee-adjusted execution edge or declares an arbitrage. Polymarket US product semantics, fees, collateral, depth, and actual liquidity must be verified independently.

## Schedule and outputs

GitHub Actions `cross-exchange-watch.yml` runs **every four hours**, and can be run manually. It writes:
- `outputs/cross_exchange/latest.json`: most recent coverage and up to 30 candidate matches for investigation.
- `outputs/cross_exchange/history.jsonl`: the most recent 42 scan summaries (about one week), retaining incomplete-coverage flags.

A first successful scan is needed before any live count or market overlap claim. Pagination is deliberately capped (6 × 100 events per league), and BBO reads are capped at 80 per league. The results explicitly flag incomplete pages or capped snapshots.

**First-week research questions:** How many unique player props actually overlap? Are both sides quoted? What percentage have matching, *verified* contract language? How quickly do quotes disappear? Are apparent price gaps still present when executable depth and fees are considered? If no meaningful overlap, don't build a trader.

## Safety and operations

This job contains GET requests only and keeps all trading credentials out of the workflow. It doesn't contact the DigitalOcean server. Workflow failure means **data not verified**, not zero opportunities. No automatic promotion to demo/live trading is possible.
