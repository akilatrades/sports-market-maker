# Start here

A guide for anyone joining the project. Plan on about an hour of reading,
then a walkthrough with the owner.

## The project in one minute

- **The market.** Kalshi lists player-prop contracts such as "Will this
  player score 25+ points?" A contract pays $1 if the answer is yes and $0
  if not, so its price (say 40¢) is the market's probability (40%). Every
  contract has two sides: YES and NO.
- **The idea.** The bot only buys **NO**, and only with **resting** limit
  orders: it posts a price and waits for someone to trade with it, instead
  of paying the asking price. The people buying YES at the ask are mostly
  fans backing a player, so on average NO is slightly underpriced.
- **The filter.** Before posting, the bot estimates the real probability
  from sportsbook odds (when at least two books agree) or from the
  project's own stats model, and posts only where NO is priced at or below
  that estimate.
- **The evidence.** In a replay of the 2025–26 NBA season the rule earned
  about 3¢ per contract. That replay assumed the bot was always first in
  line and used rules chosen on that same season, so it is optimistic.
- **The current phase.** Since October 2026 the bots trade real money
  under small, fixed limits. The goal is to find out whether real fills
  earn what the replay says. Nothing is proven yet.

## Reading order (about an hour)

1. The [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/):
   results and status at a glance (5 minutes).
2. The [README](../README.md): what was tried, what worked, what did not
   (10 minutes).
3. The [project brief](PROJECT_BRIEF.md): the case study in two pages
   (10 minutes).
4. The two sections below, *How a game night works* and *Where things
   run* (5 minutes).
5. The [NBA production worker](../deploy/PROD_NBA_AUTO.md): the live order
   rules and limits (10 minutes).
6. The [research log](../RESEARCH_LOG.md): skim the headings, then read the
   decomposition entry, which is where the strategy came from (15 minutes).
7. The [forward-validation rules](FORWARD_VALIDATION.md): how live results
   are judged (5 minutes).

Files with a date in the name are snapshots of what was known that day.
Read them for history, not for how things work now.

## How a game night works (NBA)

1. **Morning and afternoon, on GitHub Actions.** Scheduled jobs refresh
   stats and injury news, build player projections, collect sportsbook
   lines (eight snapshots a day) and publish a checked input file to the
   repository.
2. **From six hours before tip-off, on the server.** Every few minutes the
   NBA worker downloads that input file, reads Kalshi's order books and,
   for each prop, compares the NO price with its estimate. Where the edge
   is big enough and every limit allows it, it posts a NO order one cent
   better than the best current bid. New orders start two to six hours
   before tip-off.
3. **Until tip-off.** Orders rest. The worker cancels an order if the edge
   disappears, if its inputs fail checks, or if a stop is hit.
4. **At tip-off.** Unfilled orders expire. They cost nothing; the cash
   comes back.
5. **After the game.** Kalshi settles each contract at $1 or $0, and the
   settled profit and loss appears on the dashboard.

The NFL worker follows the same pattern on game days, with its own,
smaller limits.

## Where things run

| Place | What runs there | Who controls it |
|---|---|---|
| GitHub Actions (public) | Data refreshes, projections, sportsbook lines, tests, dry-run order logs, the dashboard | Scheduled jobs; server actions are owner-only |
| DigitalOcean server (private) | The two funded workers (NBA and NFL) on timers, the Kalshi key, the live P&L feed | Owner only, through the Go live / Stop and Deploy buttons |
| Kalshi | The account, orders and settlement | Owner only |

Merging code does **not** change the live bots. The owner deploys a
reviewed commit to the server with a separate button
([how](../deploy/README.md)).

## Current live limits

These come straight from the code. If they disagree with any document, the
code is right.

| Limit | NBA ([`prod_nba_auto.py`](../live/prod_nba_auto.py)) | NFL ([`nfl_policy.py`](../live/nfl_policy.py)) |
|---|---:|---:|
| Contracts per order | 2 | 5 |
| Cost per order | $4 | $3 |
| Orders per game | 10 | 2 |
| Cost per game | $15 | $3 |
| Cost per team per day | $10 | $3 |
| Open orders at once | $75 | $15 |
| New orders per day | $75 | $30 |
| Minimum edge to post | 3¢ | 3¢ |
| Lifetime orders placed | $1,000 | $50 |

Across both bots ([`shared_account_risk.py`](../live/shared_account_risk.py)):
at most $90 open and $105 placed per day, and the bots stop for the day
after $20 of settled losses and for good after $60.

## Repository map

| Path | What is in it | Start with |
|---|---|---|
| `live/` | Production workers, risk limits, projections, input checks | `prod_nba_auto.py`, `shared_account_risk.py` |
| `kalshi/` | Market data, fees, fills, sportsbook consensus, signed order client | `maker.py`, `stats.py` |
| `markets/nba/`, `markets/nfl/` | Stat features and probability models | |
| `research/` | Backtests and studies behind every rule | `nba_launch_audit.py` |
| `deploy/` | Server setup, the Go live / Stop and Deploy helpers, runbooks | `README.md` |
| `.github/workflows/` | Scheduled data jobs, tests and the owner-only buttons | `droplet-control.yml` |
| `dashboard/` | The public dashboard | `index.html` |
| `tests/` | 400+ tests, including failure cases for the live workers | |
| `outputs/` | Research outputs and published snapshots | |

## Set up and try it

```bash
git clone https://github.com/<your-account>/sports-market-maker.git
cd sports-market-maker
python -m pip install -r requirements.txt   # Python 3.11 or 3.12
pytest -q                                   # offline test suite
python -m research.nba_launch_audit         # recompute the historical audit
```

None of these place orders, and none need any keys.

## Open questions, and good first projects

1. **Do live fills match the replay?** Each night, compare the orders that
   filled with what the replay predicts for the same orders, using
   Kalshi's public trade history. This is the biggest open question.
2. **How much can the strategy hold?** Estimate what share of the trading
   at our price we actually get. That number decides how far the strategy
   can scale.
3. **Does the edge hold up this season?** Keep a running out-of-sample
   scorecard for 2026–27.
4. **More markets.** Other stat types, the NFL side, other sports. Each new
   market brings new trading to fill against.

Start any of these as an entry in the research log: write the question,
the method and the pass/fail bar *before* looking at results.

## Words you will see

| Term | Meaning |
|---|---|
| Bid / ask | The best price someone will pay / accept right now |
| Spread | The gap between bid and ask |
| Tick | The smallest price step, 1¢ |
| Resting (limit) order | An order that waits on the book at a set price |
| Maker / taker | The side whose order was waiting / the side that traded against it |
| Fill | When someone trades against a resting order |
| Queue | Other orders at the same price, ahead of ours |
| Edge | Estimated fair value minus the price paid |
| Settlement | Kalshi paying $1 or $0 after the game |
| Drawdown | The biggest drop from a high point in profit to a later low |
| In-sample / out-of-sample | Tested on the data the rule was built from / on new data |
| Game-clustered | Statistics that treat props from the same game as related |

## Rules of the road

How to contribute: [CONTRIBUTING.md](../CONTRIBUTING.md). Why there is no
write access, and what stays private:
[deploy/GITHUB_ACCESS.md](../deploy/GITHUB_ACCESS.md).
