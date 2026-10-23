# Current project state

*Updated 23 October 2026. Earlier running notes, up to 19 October, are kept
unchanged in [PROJECT_STATE_NOTES_2026-10-19.md](PROJECT_STATE_NOTES_2026-10-19.md).*

## What is live

Three bots trade one small real-money Kalshi account from a private
DigitalOcean server. They share one set of account-wide caps and loss stops
([`shared_account_risk.py`](../live/shared_account_risk.py)): across all
three, trading stops for the day after $20 of realized losses and for good
after $100 (−$60 before 23 October).

| Bot | Rules | Live since | Details |
|---|---|---|---|
| NBA player props | `nba-no-v6-three-contracts`: three-contract post-only NO orders, one cent inside the spread, 2–6 hours before tip-off, resting until tip-off, 0–15¢ of estimated edge | 20 October (v5 from 21 October, v6 once deployed after 23 October) | [PROD_NBA_AUTO.md](../deploy/PROD_NBA_AUTO.md) |
| NFL receiving yards | `nfl-no-v3-baseline-quote`: the same idea with smaller limits | 19 October | [PROD_NFL_AUTO.md](../deploy/PROD_NFL_AUTO.md) |
| Spread maker | `spread-maker-v3-24h-starts`: YES and NO bids one cent inside 8¢+ spreads in 61 series, only before a known event start, from 24 hours before expiry, up to 2 contracts, $60 open | 22 October (v2 from 23 October, v3 once deployed) | [PROD_SPREAD_AUTO.md](../deploy/PROD_SPREAD_AUTO.md) |

- **Deployed code:** the merge of pull request #80 (23 October), which
  includes #79. The owner deploys with **Deploy funded worker code →
  DEPLOY_CODE**; merging alone changes nothing on the server.
- **Limits** come from the code and are summarized in
  [START_HERE.md](START_HERE.md#current-live-limits).
- **Retired:** the older research runner (`market-maker.timer`) is disabled
  on the server, and `live/nba_trade.py` refuses to send live orders to the
  production exchange. Its dry-run order logs are still published from
  GitHub Actions.

## What the evidence shows so far

| Market | Accepted orders | Filled orders | Settled markets | Realized P&L | As of |
|---|---:|---:|---:|---:|---|
| NFL receiving yards | 10 | 4 | 4 | −$0.69 | 19 Oct |
| NBA player props | 9 | 1 | 1 | Positive (amount private) | 21 Oct |

These are the last signed, published reconciliations. Later live results
are on the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/)
(verified settlements only) and in the owner's private fills export. This
is operational evidence that ordering, reconciliation and settlement work;
it says nothing yet about profitability.

Each bot is judged at a checkpoint written before it went live
(`python -m research.live_checkpoint --data <private export>`):
- **NBA v5 and v6 together:** 1,900 settled filled orders, the $5,000
  allowance or 30 days from the first v5 order.
- **Spread maker v3:** 300 filled contracts or 4 weeks, on its own orders.

## What is still unknown

1. **Live fill share.** The replays assume the bot is always first in line
   at its price. The spread maker now measures its real share after every
   live pass; the NBA bot measures volume-weighted capture.
2. **Out-of-sample edge.** The rules were chosen on 2025–26 data. The
   2026–27 season is the real test.
3. **Capacity.** How large orders can get before fills thin out.
4. **How many spread markets v2 can quote.** It needs a known start; with
   start times from event tickers alone it keeps about a sixth of v1's
   simulated profit. Kalshi's milestone start times, trusted by type, add
   more; how many is being measured.

## Recent changes

- **22 October:** the spread maker pilot went live (5 contracts per order,
  $60 open, its own −$10 daily and −$40 total stops); it joined the
  private fills export and the dashboard; Kalshi balance reads retry on
  rate limits.
- **22–23 October:** live fill share and the checkpoint report (PR #79); a
  one-page case study, design decisions and a reading guide.
- **22–23 October (overnight):** on its first night the spread maker
  quoted a college football game after kickoff, because its window counted
  from Kalshi's expected expiration. I paused it; v2 quotes only before a
  known start (PR #80), after three rounds of independent review.
- **23 October:** at the owner's request, NBA rules v6 trade 3 contracts an
  order (was 1), with $50 per game (was $25) and a $5,000 allowance (was
  $2,000); NBA's own and the account-wide total loss stops move from −$60
  to −$100. A replay showed 6–7¢ spreads earned nothing pregame, so the
  spread maker stays at 8¢ ([research log](../RESEARCH_LOG.md)).
- **23 October:** a pre-registered study of 64 series found that quoting
  from 24 hours before expiry, with start times from validated Kalshi
  milestone types and each series' usual timing, gives about 9× the
  pregame fills (simulated, in-sample). It also found esports milestones
  are often late, so they are never trusted. Spread maker v3 adopts it at
  2 contracts a side, tightened after review: the earlier of milestone and
  series estimate counts, estimates use the 99th-percentile gap, a start
  never moves later, the Brent, S&P 500 and 10-year note dailies are left
  out and the daily order cap is 1,500. Replayed, 6.5× v2's pregame fills
  at +9.0¢ a contract (simulated, in-sample).

## Where to look

- Live status: the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/),
  or **Go live / Stop funded bots → STATUS** (owner).
- How everything runs: the [operations guide](../deploy/README.md).
- Why each rule exists: the [research log](../RESEARCH_LOG.md).
