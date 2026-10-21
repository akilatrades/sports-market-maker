# Current project state

*Updated 21 October 2026. Earlier running notes, up to 19 October, are kept
unchanged in [PROJECT_STATE_NOTES_2026-10-19.md](PROJECT_STATE_NOTES_2026-10-19.md).*

## What is live

- **Two funded bots trade real money on Kalshi** from a DigitalOcean
  server: one for NBA player props and one for NFL player props. Both were
  switched on with the owner-only [Go live / Stop button](../deploy/GO_LIVE_BUTTON.md)
  and share one small account.
- **Deployed code:** the commit from pull request #63 (21 October). It
  added account-wide loss stops, a 15-minute hold when input downloads fail
  for connection reasons, and a fix for the NFL sportsbook file format.
- **NBA rules** (`nba-no-v4-smaller-orders-edge3-baseline`): post-only NO
  orders one cent inside the spread, started 2–6 hours before tip-off and
  resting until tip-off, with at least 3¢ of estimated edge to be placed
  and to stay. [Details and limits](../deploy/PROD_NBA_AUTO.md).
- **NFL rules** (`nfl-no-v3-baseline-quote`): the same idea with smaller
  limits. [Details](../deploy/PROD_NFL_AUTO.md).
- **Risk limits** are in the code and summarized in
  [START_HERE.md](START_HERE.md#current-live-limits). Across both bots the
  account stops for the day after $20 of settled losses and for good after
  $60.
- **Retired:** the older research runner (`market-maker.timer`) is
  disabled on the server, and `live/nba_trade.py` refuses to send live
  orders to the production exchange. Its dry-run order logs are still
  published from GitHub Actions.

## What the evidence shows so far

| Market | Accepted orders | Filled orders | Settled markets | Realized P&L | As of |
|---|---:|---:|---:|---:|---|
| NFL receiving yards | 10 | 4 | 4 | −$0.69 | 19 Oct |
| NBA player props | 9 | 1 | 1 | Positive (amount private) | 21 Oct |

This is operational evidence that ordering, reconciliation and settlement
work. It says nothing yet about profitability. Live results are judged by
the [forward-validation rules](FORWARD_VALIDATION.md): a review after 30
days and 500 settled fills.

## What is still unknown

1. **Live fill rate.** The replay assumes the bot is always first in line
   at its price. Real queue position will cut fills; by how much is the
   main open question.
2. **Out-of-sample edge.** The rules were chosen on the 2025–26 season.
   The 2026–27 season is the real test.
3. **Capacity.** How large the orders can get before fills thin out and
   other traders react.

## Recent changes

- **20–21 October:** NBA v4 rules (rest until tip-off, one-cent
  improvement only); the Go live / Stop button; limits sized for the small
  account; account-wide loss stops; the connection-only input hold; the
  NFL sportsbook file fix.
- **21 October:** repository access hardening (server workflows are
  owner-only, manual and run only from `main`; their jobs name the
  `funded-droplet` environment that the server secrets move into), a
  full-history secret scan (clean), retired legacy server workflows
  removed, and new [start-here](START_HERE.md),
  [contributing](../CONTRIBUTING.md) and [security](../SECURITY.md) guides.

## Where to look

- Live status: the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/),
  or **Go live / Stop funded bots → STATUS** (owner).
- How everything runs: the [operations guide](../deploy/README.md).
- Why each rule exists: the [research log](../RESEARCH_LOG.md).
