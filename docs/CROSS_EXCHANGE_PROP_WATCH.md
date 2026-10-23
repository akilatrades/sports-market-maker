# Cross-exchange prop watch: Kalshi vs Polymarket US

This **research-only** job compares public NBA and NFL player-prop listings. It never authenticates with Polymarket, requires no deposit, and cannot submit or cancel orders. It never touches the production trading bots.

## Data sources

- **Polymarket US** public [league metadata](https://docs.polymarket.us/api-reference/sports/get-league-by-slug), [active prop-market catalog](https://docs.polymarket.us/api-reference/markets/get-markets), and [best bid/offer](https://docs.polymarket.us/api-reference/markets/get-market-bbo) under `https://gateway.polymarket.us`. **Not** the international Gamma/CLOB API on `polymarket.com`.
- **Kalshi production public market data** (`kalshi.api.fetch_markets`) for NBA points, rebounds, assists, threes, NFL receiving yards and anytime touchdown. This is read-only research *against production quotes*, not Kalshi Demo account executions.

## What gets counted

A Polymarket US listing is considered a candidate only when its documented sports market type identifies it as a prop (including typed player-prop metadata) and its text identifies an **explicit OVER / at-least outcome**, player, statistic and line. For Kalshi, the match uses its prop series, player, numeric strike and event date.

The two keys must match exactly on **league, Eastern game date, normalized player name, stat and threshold**. Ambiguous or missing information is excluded rather than guessed. Every candidate still needs human comparison of contract language, corrections, postponement, ties and settlement procedures before any return/arbitrage claim.

If the candidate is unique on both sides, the tool queries public Polymarket US BBO and compares both exchange's YES bid/ask quotes. It reports **midprice differences for research only**; it never calculates a fee-adjusted execution edge or declares an arbitrage. Polymarket US product semantics, fees, collateral, depth, and actual liquidity must be verified independently.

## Schedule and outputs

GitHub Actions `cross-exchange-watch.yml` runs **every four hours**, and can be run manually. The catalog is queried for each league's tag ID and `SPORTS_MARKET_TYPE_PROP`; if the API returns an empty result, the output flags it (`polymarket_us_catalog_empty`, `pagination_complete`) so the coverage reads as **unverified**, not 'there are no props on the exchange'. It writes:
- `outputs/cross_exchange/latest.json`: most recent coverage and up to 30 candidate matches for investigation.
- `outputs/cross_exchange/history.jsonl`: the most recent 42 scan summaries (about one week), retaining incomplete-coverage flags.

A first successful public-API probe ran October 17 at 23:40 UTC. Its league-tagged active `SPORTS_MARKET_TYPE_PROP` filter returned **zero** NFL and **zero** NBA market rows even though the unfiltered league-tag requests returned other market types (including futures). The same probe scanned **1,097 Kalshi NFL** and **312 Kalshi NBA** open markets. This describes the exact public catalog filter on that date; it is **not proof that Polymarket US lists no player props overall**. Do not claim additional opportunities or overlap until usable corresponding contracts are actually observed. Pagination is deliberately capped (6 × 100 filtered markets per league), and BBO reads are capped at 80 per league. The results explicitly flag incomplete pages or capped snapshots.

**Diagnostic added after the initial empty filter:** When the exact league-tagged PROP catalog returns no listings, the scanner also reads only the first page of *unfiltered* active league-tagged US listings and counts those explicitly tagged as props. This is a bounded GET-only API coverage diagnostic; it cannot establish total available inventory, contract equivalence, depth, fees or an arbitrage. An error makes its status unverified, never zero opportunities. These observations appear under `unfiltered_sample_diagnostic` in each league's coverage report.

**First-week research questions:** How many unique player props actually overlap? Are both sides quoted? What percentage have matching, *verified* contract language? How quickly do quotes disappear? Are apparent price gaps still present when executable depth and fees are considered? If no meaningful overlap, don't build a trader.

## Safety and operations

This job contains GET requests only and keeps all trading credentials out of the workflow. It doesn't contact the DigitalOcean server. Workflow failure means **data not verified**, not zero opportunities. No automatic promotion to demo/live trading is possible.
