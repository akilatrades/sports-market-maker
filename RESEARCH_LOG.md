# Research log

Decisions and results in the order they were made. Each test is written down
here before it is run, and results are added below without editing the plan.

## 2026-10-15: Plan and pre-registered market test

### Question

Can a model built from public box scores and betting lines price Kalshi's NBA
player props (points, rebounds, assists, threes) well enough to beat the price
at tip-off, after Kalshi's fees?

### Data

- **Box scores:** ESPN player and team box scores from the sportsdataverse
  hoopR data repository, 2015-16 to 2025-26, regular season and playoffs,
  including players who did not play and the listed reason.
- **Betting lines:** consensus closing spread and total for each game
  (The Odds API, via the same repository), available from 2020-21.
- **Kalshi prices:** every settled market in the series KXNBAPTS, KXNBAREB,
  KXNBAAST and KXNBA3PT for 2025-26 games, with hourly candles (yes bid,
  yes ask, last price, volume) around each game, from Kalshi's public
  historical API. Downloaded by `research/backfill_kalshi.py` in GitHub
  Actions starting 2026-10-15.

### Split

- **Development:** walk-forward over 2021-22 to 2024-25. Before each calendar
  month the model is refit on all earlier games and predicts that month.
  Features, half-lives and shrinkage may be chosen by looking at these
  seasons.
- **Holdout:** 2025-26, regular season, play-in and playoffs. It is run once,
  with the model frozen; the commit hash of the frozen model is recorded here
  before the run.
- **Kalshi prices are not examined before the holdout run.** Until the model
  is frozen, the price files are used only for counts and for matching
  tickers to players and games (names, teams, dates), never for prices,
  results or volumes.

### Market test (fixed now, before any price is seen)

**Sample.** Every settled market in the four series for a 2025-26 regular
season, play-in or playoff game that settled yes or no. Markets settled at a
fixed value ("scalar", which Kalshi uses when the player does not play) are
excluded, as are players who cannot be matched to a box score row.

**Price.** The last hourly candle ending at or before the scheduled tip-off.
Only two-sided quotes count: yes bid above 0, yes ask below $1, and ask above
bid. Buying yes costs the ask; buying no costs one minus the bid.

**Model probability.** P(stat at or above the contract's threshold) from the
frozen model, refit before each month on all earlier games, exactly as in the
development backtest.

**Test A, information.** A logistic regression of the outcome on
logit(market mid) and logit(model probability), with standard errors
clustered by game. The model adds information the market lacks if the
coefficient on the model has t of at least 2.0.

**Test B, trading.** Buy one yes contract at the ask when
p − ask − fee(ask) ≥ 0.05; buy one no contract at 1 − bid when
(1 − p) − (1 − bid) − fee(1 − bid) ≥ 0.05. The fee is Kalshi's
0.07 × P × (1 − P) per contract. P&L is per contract, after fees, with all
four stats pooled. The rule **passes** only if all three hold:

1. mean P&L per contract above zero with t of at least 2.0, standard errors
   clustered by game (several lines for the same player and game move
   together);
2. positive in both halves: games before 2026-02-01, and games from
   2026-02-01 on, including the playoffs;
3. still positive with a stricter 0.08 threshold.

Results by stat are reported but are not used to pick a winner after the fact.

**Reported, not used for the pass/fail decision:**

- fees rounded up to the cent per contract, as for one-contract orders;
- prices from the last candle ending at least two hours before tip-off;
- the model without the teammates-out features. In the backtest those use who
  actually sat, which a final injury report shows in most cases but not for
  late scratches, so this check bounds the head start that gives the model;
- results by stat and by traded volume.

**Known limits.** Hourly candles give the top of the book, not its depth, so
size at those prices is not known. A pass would justify paper trading, not
money.

## 2026-10-15: Development results; model frozen

**Model** (`markets/nba/features.py`, `markets/nba/marginals.py`): for each stat a
Poisson regression on expected minutes (recent minutes, minutes last game,
share of starts, team games missed, teammates out or back, back-to-back,
playoffs, home, size of the spread), the player's per-minute rate shrunk
toward his position, his recent average, the team's implied points, what the
opponent allows relative to the league, and the share of that stat belonging
to regulars who are out or returning. The spread of outcomes is the
empirical distribution of actual ÷ expected by band of expected value,
separately for players averaging under 20, 20–30 and 30+ minutes.

**Development backtest**, 2021-22 to 2024-25, refit before every month on all
earlier games (99,833 player-games per stat; regulars who played, with 5+
earlier games and 10+ recent minutes):

| Stat | Typical miss, model vs recent average | Brier improvement | Log loss improvement | Players averaging 26+ minutes: Brier improvement |
|---|---|---|---|---|
| Points | 4.72 vs 4.83 | 2.1% | 2.3% | 1.3% |
| Rebounds | 1.94 vs 1.98 | 1.9% | 2.0% | 0.6% |
| Assists | 1.36 vs 1.39 | 2.6% | 2.8% | 1.5% |
| Threes | 0.91 vs 0.93 | 1.9% | 2.0% | 1.4% |

Predicted and actual rates agree to within 0.3 percentage points in every
probability band ([calibration](outputs/backtest/development/calibration.csv)).

Choices made while looking at these seasons: keeping the outcome spread by
minutes tier (it fixed a 1-point underestimate of low lines for heavy-minute
players), counting only regulars (15+ minutes) as teammates out or back,
and a five-game half-life for recent form (three and eight games were tried;
neither was clearly better). A bug in the games-missed count was found by a
unit test and fixed; it barely changed the results.

**Frozen.** The model used for the holdout season and the market test is
commit `ce26c24`. Changes after this point will be logged and the holdout
results reported for the frozen version.

**Clarification to the market test, written before any price is examined:**
the model prices players with at least 5 earlier games and 10+ recent minutes
(as in the backtest), so Kalshi markets on other players (mostly rookies in
their first games) are excluded and counted.

## 2026-10-15: Holdout season (2025-26), box scores only

The frozen model (`ce26c24`), refit before each month, run once on the
2025-26 regular season, play-in and playoffs (25,511 player-games per stat):

| Stat | Typical miss, model vs recent average | Brier improvement | Players averaging 26+ minutes: Brier improvement |
|---|---|---|---|
| Points | 4.70 vs 4.80 | 2.0% | 0.8% |
| Rebounds | 1.92 vs 1.96 | 2.3% | 0.8% |
| Assists | 1.38 vs 1.41 | 2.0% | 0.5% |
| Threes | 0.93 vs 0.94 | 1.6% | 0.9% |

Calibration held: predicted and actual rates agree to within 0.6 percentage
points in every band, with a slight lean high between 20% and 50%
([calibration](outputs/backtest/holdout/calibration.csv)). The gain over a
player's recent average is smaller for heavy-minute players, the ones Kalshi
lists, than for the whole league (about 0.5–0.9% against 1.6–2.3%).

## 2026-10-15: Kalshi download and matching (before the market test)

The backfill finished in one run: 80,582 settled markets for 2025-26 games
(points 23,562, rebounds 22,656, assists 17,745, threes 16,619), from
2025-11-18 (Kalshi's first NBA player props) to the Finals, and hourly candles
for the 67,513 that settled yes or no and traded.

Matching markets to box scores used tickers, titles, dates and teams only.
It found that Kalshi's titles read "Anthony Edwards records 40+ points" until
January 2026 and "Anthony Edwards: 40+ points" after, so the parser now takes
the player's name from the yes subtitle, which never changed format. After
that fix 78,130 of the 80,413 markets on regular-season, play-in and playoff
games match a player in that game's box score, and 77,234 are on players the
model prices. Most of the rest are players who were inactive and missing from
the box score; checking the settlement type (not the result) of the
unmatched markets showed all but 11 were settled at a fixed value, which the
test excludes anyway. No prices, yes/no results or volumes were looked at.

The market test runs next, once, with the frozen model.

## 2026-10-15: Market test results (run once, frozen model `ce26c24`)

**Sample:** 57,111 markets in 1,072 games that settled yes or no, on players
the model prices, with a two-sided quote at the last hourly candle before
tip-off. Kalshi's settlement agreed with the box score in 99.98% of markets.

**Test A: passed.** Logistic regression of the outcome on logit(mid) and
logit(model), standard errors clustered by game: market 0.560 (t 17.9),
model 0.436 (t 13.8). It passed for each stat on its own as well (model t
5.3 for points, 9.0 rebounds, 7.4 assists, 10.3 threes). Brier score: market
mid 0.1805, model 0.1812.

**Test B: failed.** 12,495 trades, −0.93¢ per contract after fees, t −1.49.
Criterion 1 fails (mean below zero), criterion 2 fails (before February
−3.35¢, t −2.50; February on −0.35¢, t −0.50), criterion 3 fails (0.08
threshold: 6,933 trades, −0.93¢, t −1.13).

Reported, not used for the decision:

| Variant | Trades | ¢ per contract | t |
|---|---:|---:|---:|
| Fees rounded up to the cent | 12,495 | −1.35 | −2.17 |
| Prices two hours before tip-off | 11,817 | −0.38 | −0.61 |
| Without the teammates-out features | 12,130 | −0.76 | −1.23 |
| Points | 4,807 | −2.00 | −2.33 |
| Rebounds | 3,195 | −1.41 | −1.20 |
| Assists | 2,960 | −0.25 | −0.21 |
| Threes | 1,533 | +2.15 | +1.44 |
| Markets with volume below the median | 4,183 | −1.06 | −1.20 |
| Markets with volume at or above the median | 8,312 | −0.86 | −1.11 |

The positive threes figure is one of four stats, not significant, and found
after the fact; it is not a result.

**Diagnostics, after the test.** Buying every yes at the ask lost 3.4¢ per
contract and every no 6.0¢ (median spread 4¢, average fee 1.2¢), so the
model's side selection was worth something, but less than the cost of
trading. Realised P&L did not rise with the model's claimed edge: claimed
6.4¢, 9.7¢, 15.0¢ and 25.3¢ realised −0.9¢, −0.9¢, −1.3¢ and +0.4¢. Across
probability bands outcomes happened about 1.3 points more often than the mid
price implied (t 3.9), but not by enough to cover the cost of buying yes.

**Exploratory, not pre-registered:** a blend of model and market, with
weights refit each month on earlier months only (the model's weight fell
from 0.81 in December to 0.43 by the Finals), traded with the same rule,
lost 2.1¢ per contract (6,551 trades, t −2.57). The blend's Brier score
(0.17889) beat the mid's (0.17910) by 0.1%.

**Conclusion.** The model holds real information the tip-off price lacks,
but on Kalshi's NBA props it is worth less than the spread and fee. No
trading rule from this work is recommended for money.

**Forward test for 2026-27 (fixed now).** The same Test A and Test B, run on
2026-27 markets from the logged snapshots and the projections the model
makes before each game, at the end of January 2027 and again after the
Finals; plus the same rule priced at the morning snapshot. Any change to the
model before then is logged here with its date.

## 2026-10-15: Exploratory findings and the rule for 2026-27

Everything in this entry was found after the market test failed, on the same
2025-26 markets. It is in-sample and is recorded so the choices can be
checked; it proves nothing until 2026-27 confirms it
(`research/strategy_backtest.py`, `outputs/strategy/`).

**Where the money went.** Priced at the mid, with no spread or fee, the
model's picks made +2.4¢ per contract (t 3.9). Buying at the ask and paying
the fee cost 3.3¢ on average. By spread at tip-off: 1¢ spread +2.1¢ per
contract (3,884 trades), 2¢ +0.7¢, 3–4¢ −1.6¢, 5¢ or more −5.5¢. With
spreads of 2¢ or less, prices taken 2, 4 and 6 hours before tip-off gave
+2.3¢, +1.9¢ and +2.8¢ (t 2.7, 2.1, 3.1), and +2.1¢ to +2.4¢ with the
teammates-out features switched off
([grid](outputs/strategy/exploratory_grid.csv)).

**The rule** (`kalshi/strategy.py`): price taken 2–6 hours before tip-off;
spread of 2¢ or less; the model's edge at least 5¢ after the fee; one line
per player, stat and game; live, skip anyone on the injury report. Staking:
1% of the bankroll per position, at most $25 or 100 contracts, at most 30%
of the bankroll per day.

**Replayed on 2025-26** with two looks per game (5 and 2 hours before
tip-off, about what the live schedule gives): 3,928 positions, +1.9¢ per
contract (t 2.3), 6.2% per dollar risked.

**But it all came from the playoffs.** Regular season: 2,493 positions,
+0.02¢ per contract (t 0.03), 0.1% per dollar. Play-in and playoffs: 1,435
positions in 91 games, +5.1¢ per contract (t 3.6), 16.7% per dollar, 85% of
them on the "no" side. A $500 bankroll at these stakes went to $390 by early
January, $509 by April 10, and $2,618 by the Finals.

$500 bankroll, 2,000 resampled seasons (whole days resampled with
replacement):

| Part of season | Edge assumed | Median end | 1 in 10 ends below | Chance of a loss | Typical worst drawdown |
|---|---|---:|---:|---:|---:|
| Regular season | as in 2025-26 (none) | $496 | $235 | 50% | 46% |
| Play-in and playoffs | as in 2025-26 | $2,907 | $1,494 | 0% | 17% |
| Play-in and playoffs | half of 2025-26 | $1,233 | $610 | 5% | 28% |
| Play-in and playoffs | none | $513 | $251 | 48% | 44% |

The playoff result is one postseason, found by splitting the season after
seeing it, with a rule also chosen on that season. Half the edge is the
planning case, and no edge is entirely possible.

**Forward test for 2026-27 (fixed now, before any 2026-27 price exists).**
The projections workflow runs four times a day and adds the rule's positions
to `outputs/paper/ledger.csv`, sized from a $500 paper bankroll, settled from
Kalshi's own settlement of each market.

1. *Regular season* (to the end of the 2026-27 regular season): the rule
   passes if its positions return more than zero per dollar with
   game-clustered t of at least 2.0 on profit per contract. Paper only; the
   expectation from 2025-26 is about zero.
2. *Play-in and playoffs 2027*: the same test on those positions alone. This
   is the real test of the playoff finding. Whether to use money is the
   account holder's decision; the evidence for it is the in-sample result
   above and nothing else.
3. The rule and model are not changed during the season. Bug fixes are
   logged here with their date.

The original market test at tip-off (Test A and B) is also rerun on 2026-27
as planned.

## 2026-10-15: Three new ideas, tests fixed before their data is downloaded

The first approach (out-predict the price and pay the spread) failed. Three
different sources of edge are tested on 2025-26. Each test below is written
before the data it needs is downloaded: Kalshi's trade history (idea 1),
sportsbook prop lines (idea 2) and double-double and triple-double markets
(idea 3). Ideas 1 and 3 reuse 2025-26 prop prices and results that have
already been seen; this is stated, not hidden.

Common pass criteria for a trading test: profit per contract above zero with
game-clustered t of at least 2.0; positive in the regular season on its own;
positive both before and from 2026-02-01. Positions are one per player, stat
and game (the line with the largest edge), placed at the first of two looks:
the last hourly candle ending at least 5 hours before tip-off, then at least
2 hours before.

### Idea 1: be the maker (limit orders)

- **Universe:** the 57,111 markets priced in the market test.
- **Order:** on the side the model favours, rest a buy order one cent above
  that side's best bid when the spread is at least 2 cents (then the order
  is alone at the best price), or at the bid when the spread is 1 cent (then
  it joins a queue of unknown size). Placed only if the model's probability
  for that side, minus the order price, minus the maker fee is at least
  3 cents. Cancelled at tip-off.
- **Fill:** from Kalshi's trade prints between placement and tip-off. A
  resting yes order at price q fills if a taker sells yes (taker outcome side
  "no") at a yes price below q, or at q when the order improved the bid; a
  joined order needs a print strictly through its price. No order fills more
  than the contracts that traded.
- **Fee:** primary, a maker fee of a quarter of the taker fee
  (0.0175 × P × (1 − P)); also reported with no maker fee.
- **Reported:** fill rate, and adverse selection: profit on filled orders
  against what the same orders would have made had they all filled.

### Idea 2: copy the sportsbooks

ESPN's public odds API is probed for stored DraftKings player-prop lines on
2025-26 games. If they exist for most games: the book's over/under is turned
into a no-vig probability at its line, moved to each Kalshi line using the
model's distribution shape (the model's expected value is shifted until it
matches the book at the book's line), and compared with Kalshi's price at
the last candle before tip-off (the book's stored line is taken to be its
closing line, so earlier Kalshi prices would see the future). Buy the side
where the book-based probability beats cost plus fee by 3 cents or more.
If no free history exists, this idea cannot be tested without buying data,
and that decision is the account holder's.

### Idea 3: structure and correlation

- **Ladder arbitrage:** for every player, stat, game and hourly candle,
  check whether buying yes on a lower line and no on a higher line costs
  less than $1 after taker fees. That pair pays at least $1 whatever happens.
  Counted, with the first opportunity per player, stat and game priced.
- **Double-doubles:** a fair price for "at least two of points, rebounds,
  assists of 10 or more", with each probability taken from Kalshi's own
  10+ market for that player and stat at the same hour (its mid price), or
  the model when Kalshi has no such market, and the three combined with a
  Gaussian copula whose correlations are fitted on 2021-22 to 2024-25 model
  predictions and results (before any double-double price is downloaded).
  Buy the side where this fair price beats cost plus taker fee by 5 cents.
  Same pass criteria. Also reported: Brier scores of Kalshi's double-double
  price, the fair price, and the price assuming independence.
- **Triple-doubles:** the same, reported only (they are rare).

## 2026-10-15: Results for the three new ideas

Run once each as written above (`research/new_ideas.py`,
[results](outputs/new_ideas/results.json)). Data downloaded after the tests
were committed: 657,723 Kalshi trade prints in the six hours before tip-off,
4,879 double-double and 1,171 triple-double markets, and ESPN's stored
sportsbook props for every 2025-26 game.

### Idea 1, be the maker: passed

14,516 resting orders; 31% filled (59% of orders on the "no" side, 7% on
the "yes" side). Filled orders, with a maker fee of a quarter of the taker
fee: **+3.1¢ per contract, t 4.1**, 4,541 fills in 854 games. Regular season
+2.6¢ (t 3.0); playoffs +4.5¢; before February +2.3¢; from February +3.3¢.
All criteria pass. With no maker fee: +3.7¢ (t 4.8).

Adverse selection is large: had every order filled it would have made
+11.3¢ per contract; the orders that did not fill would have made +15.0¢.
Orders fill mostly when the market moves against them, but the ones that
fill still made money.

Reported checks: every fill requiring a trade through the price, +3.0¢
(t 3.6); the model without the teammates-out features, +3.8¢ (t 5.0); "no"
orders +3.5¢ (t 4.2), "yes" orders +0.1¢ (t 0.1). Return per dollar on
filled orders 10.8%. Recomputed with separate code
(`research/verify_maker.py`): identical.

$500 bankroll (each order reserves its cost while it rests; 1% per order,
day's orders capped at 30% of the bankroll, fills limited to the contracts
that traded through): the 2025-26 replay ends at $2,143 with a 13% worst
drawdown. Resampling days 2,000 times: median $2,010 (1 in 10 below
$1,203); with half the edge, median $953 (1 in 10 below $550, 6% chance of a
loss); with no edge, median $445 (61% chance of a loss).

Limits: the simulation cannot know how other traders would have reacted to
these orders; an order alone at a new best price is assumed first in line;
the maker fee for these series is assumed, not confirmed; and about 80
orders a day must be placed and cancelled at tip-off, which needs a program
using a Kalshi API key.

### Idea 2, copy the sportsbooks: not testable for free

ESPN stores sportsbook props for 176 of the 1,072 games with Kalshi props
(ESPN BET for 76 games in November, DraftKings for 100, mostly playoffs).
The stored rows do not say which price is the over and which the under (in
ESPN BET's data the order is unrelated to the result), and the stored times
are morning lines, not closing lines. The pre-registered test needs most
games, so it was not run. Testing it needs a paid historical prop feed, or
logging sportsbook lines from now on.

### Idea 3, structure and correlation: failed

- **Ladder arbitrage:** 6 of 116,307 hourly snapshots with two or more lines
  had a riskless pair after fees, worth 0.2¢ on average. Kalshi keeps its
  ladders consistent.
- **Double-doubles:** the correlations are real (treating the stats as
  independent underprices double-doubles by about a tenth), but Kalshi
  already prices them: Brier score of Kalshi's mid 0.1331, the correlated
  fair price 0.1327, independence 0.1330 (3,607 markets). The rule made 243
  trades at −1.7¢ per contract (t −0.7). Failed.
- **Triple-doubles (reported only):** Kalshi's mid averaged 10.1% against
  7.2% happening and a fair price of 7.7% (697 markets); its Brier score was
  worse than the fair price's (0.0569 against 0.0527). Only 16 trades
  cleared the 5¢ edge, so this is an observation, not a result.

### What this means

The model's edge is real but small; the way to keep it is to provide
liquidity rather than take it. Resting orders on the model's side, mostly
offering "no" just inside the ask, made money in both halves of the season
and in the regular season on its own. It is the one approach so far that
passed a test fixed before its data was seen.

## 2026-10-15: The "no" seller, and the live paper tests for 2026-27

**Exploratory, after idea 1 passed (same 2025-26 data, in-sample).** Resting
"no" orders with no model at all (one per player, stat and game, on the
lowest line) made +2.8¢ per filled contract (8,409 fills, t 5.3); "yes"
orders everywhere lost 2.0¢ (t −1.8). Kalshi's prop traders mostly buy
"yes", and selling them "no" one cent inside the ask paid. Variants tried:

| No-side orders on | Model veto | Fills | ¢ per contract | t | Regular season ¢ |
|---|---|---:|---:|---:|---:|
| lowest line per player and stat | none | 8,409 | +2.79 | 5.3 | +2.79 |
| every line | none | 33,475 | +1.65 | 4.1 | +1.35 |
| lowest line | skip if model edge < −3¢ | 7,271 | +3.17 | 5.7 | +3.03 |
| every line | skip if model edge < −3¢ | 26,449 | +2.32 | 5.3 | +1.96 |
| lowest line | skip if model edge < 0 | 6,277 | +3.55 | 6.0 | +3.54 |
| every line | skip if model edge < 0 | 21,373 | +2.88 | 6.1 | +2.45 |

Fills in the last 30 minutes before tip-off made the most (+7.2¢); cancelling
30 minutes early cut profit by about a fifth, so orders stay up to tip-off.

**Chosen for 2026-27: every line, skipping any order the model rates below
zero.** It is the most diversified (most fills, smallest worst day) and the
veto is the model's only job. These figures are in-sample and are not
evidence; the 2026-27 season is.

### Live paper tests, fixed before opening night (2026-10-20)

Two resting-order rules are paper traded from separate $500 paper
bankrolls, alongside the taker rule already running:

1. **Model side (idea 1, as tested):** on the side the model favours, one
   cent above that side's bid when the spread is 2¢ or more, else at the
   bid; only if the model's edge after the maker fee is at least 3¢; one
   order per player, stat and game, the largest edge.
2. **"No" seller:** a "no" order on every line, one cent above the "no"
   bid when the spread is 2¢ or more, else at the bid; skipped if the
   model's probability of "no", minus the order price and the maker fee, is
   below zero.

Both: orders are posted by the first projection run 2 to 6 hours before
tip-off and cancelled at tip-off; players on the injury report are skipped;
each order is sized at 1% of that rule's paper bankroll (whole contracts, at
most $25 or 100 contracts), and a day's orders together reserve at most 30%
of it. An order fills with as many contracts as traded through its price
between posting and tip-off, read from Kalshi's public trade prints with the
same rules as the backtest. Filled positions are settled from Kalshi's
settlement. Maker fee assumed at a quarter of the taker fee until Kalshi's
schedule for these series is confirmed.

**Pass criteria for each rule, judged at the end of the 2026-27 regular
season:** profit per filled contract above zero with game-clustered t of at
least 2.0, and positive both before and from 2027-02-01. A checkpoint on
2027-01-31 is reported but decides nothing. No rule changes during the
season; bug fixes are logged here with their dates.

## 2026-10-15: In-game test, fixed before it is run

Kalshi's prop markets keep trading during games. The question: does a model
that updates on the live game state price them better than the market?

- **Game state** from ESPN play-by-play (sportsdataverse hoopR), which
  timestamps every play: each player's points, rebounds, assists and threes
  so far, minutes on court so far (lineups rebuilt from substitutions),
  personal fouls, whether he is on the court, the score margin and the game
  time left.
- **In-game model:** the stat still to come, as a Poisson regression on the
  pre-game expected value (the frozen walk-forward model), game time left,
  minutes so far against his usual share, fouls, being on court, margin and
  the stat so far; the spread of outcomes as before (empirical, by band of
  expected value). Fitted on 2023-24 and 2024-25 games only (states every
  six game minutes). Calibration on 2024-25 is checked with a model fitted on
  2023-24 alone before anything touches Kalshi prices.
- **Prices:** every hourly Kalshi candle that closes while the game is in
  progress (more than five minutes after the first play and before the last),
  for the 57,111 priced 2025-26 markets, with a two-sided quote, the line not
  yet reached and the player not fouled out. The state is taken from plays
  stamped at or before the candle's close.
- **Test A:** logistic regression of the outcome on logit(mid) and
  logit(in-game model), standard errors clustered by game; passes if the
  model's t is at least 2.0.
- **Test B:** buy the side the in-game model rates at least 5¢ better than
  the ask (yes) or 1 − bid (no) after the taker fee; one position per player,
  stat and game, at the first in-game snapshot where one qualifies, largest
  edge. Same pass criteria as the other tests (t ≥ 2.0 clustered by game;
  positive in the regular season alone; positive before and from February).
- **Known limits:** a real trader sees plays seconds to minutes after they
  happen, and broadcast viewers may move prices first; hourly candles show
  the best bid and ask at that instant only.

## 2026-10-15: Results: in-game test, and liquidity rewards

### In-game: passed, but the edge is speed

Run once as written above (`research/ingame.py`,
[results](outputs/ingame/results.json)). The state rebuilt from play-by-play
matches the box scores (stats exactly; minutes within about 0.8), and the
in-game model fitted on 2023-24 alone was calibrated on 2024-25 within half
a point at every tested line ([calibration](outputs/ingame/calibration_2024_25.csv)).

- 47,570 in-game snapshots of 30,529 markets in 985 games.
- **Test A: passed.** Model weight 0.79 (t 36.5) against the market mid's
  0.34; Brier score 0.168 for the model against 0.192 for the mid (in-game
  spreads are wide, median 11¢ on the trades, so the mid is a rough price).
- **Test B: passed.** 4,978 trades, **+4.2¢ per contract (t 6.3)**; regular
  season +3.6¢ (t 4.2); playoffs +5.4¢; before February +8.1¢, from February
  +3.8¢. Recomputed with separate code: identical. Game states spot-checked
  against the raw play-by-play: identical.

Reported checks. The same test with the game state taken from before the
quote, as if the trader's feed were late:

| State known | ¢ per contract | t | Regular season ¢ |
|---|---:|---:|---:|
| at the quote | +4.2 | 6.3 | +3.6 |
| 1 minute late | +3.2 | 4.6 | +2.5 |
| 3 minutes late | +2.2 | 3.1 | +1.1 |
| 5 minutes late | +0.3 | 0.5 | −0.9 |

The model's information advantage (Test A) is the same at every delay; the
profit is not. Most of it comes from quotes that have not yet caught up with
the game, and it is gone if the trader is five minutes behind. By part of
the game: first half +3.8¢, third quarter +4.5¢, fourth quarter +7.0¢ (where
spreads are widest, median 25¢, and volume thinnest). On court +4.3¢, on the
bench +4.2¢.

Limits: hourly candles show the book at one instant, not its depth; the
median hourly volume in these markets was about 360 contracts. Doing this
live needs a program that reads plays and Kalshi's order book within seconds.

### Liquidity rewards: almost none on NBA props

Kalshi's public list of incentive programs (325,341 programs, all statuses)
has only 8 on NBA player props, all on points, all ended, $800 in total.
The rewards go to other markets: daily temperature highs (Miami alone
$866,800 over all programs), Rotten Tomatoes scores, 15-minute crypto
prices, tennis, elections, AAA gasoline prices, and NFL fantasy-points
ladders ($124,800). Open now: YouTube views, Rotten Tomatoes, headlines,
AAA gasoline (monthly and New Jersey weekly), crypto. A daily job keeps
`outputs/incentives/` current.

## 2026-10-15: Parlays, fixed before they are run

Akila's question: does combining two or three high-probability plays into a
parlay make more money? A parlay pays only if every leg hits, and its fair
price is the product of the legs' probabilities (if they are independent),
so it compounds whatever edge or cost each leg has. It can only help if the
legs have an edge or if their correlation is priced wrong.

Caveat: this uses the same 2025-26 prices as the market test, whose taker
results are already known (buying single legs at the ask did not pay), so it
is not a blind test of new data.

**Legs.** The 2025-26 markets of the market test, priced from the last hourly
candle at or before tip-off with a two-sided quote, and the frozen model. A
leg is the side the model favours; q is the model's probability for that
side, c its cost (the ask for yes, 1 - bid for no). A leg qualifies when
q >= 0.70 ("high percentage") and q - c - fee(c) >= 0.03 (value after the
taker fee 0.07 x c x (1 - c)). At most one leg per player and game (the one
with the highest q).

**Test P1, nightly parlays across games.** On each date, keep each game's
best qualifying leg (highest q, then largest edge), rank those by q, and
form one 2-leg parlay from the top two and one 3-leg parlay from the top
three (dates with too few games are skipped). The parlay is priced at the
product of the legs' costs, the best a buyer could do (it equals buying the
legs and rolling the winnings; a real combo price adds a margin), with the
fee 0.07 x P x (1 - P) on the combined price P, and pays $1 if every leg
hits. Return per dollar staked = payout / (P + fee) - 1, one parlay per date,
so dates are independent. Each of the 2- and 3-leg rules passes if its mean
return per dollar is positive with t >= 2.0, positive in both halves (before
and from 2026-02-01) and positive in the regular season alone. Compared with
staking the same legs as single bets.

**Reported, not tested.** Every 2- and 3-leg combination of qualifying legs
from different games on the same date (t clustered by date); hit rates
against the model's and the price's implied rates; and, for pairs of legs in
the same game (same player, teammates, opponents), how often both hit
against the product of their probabilities, which is the correlation a
same-game parlay price would have to include.

**$500.** If a rule passes: 2% of the bankroll per parlay, one a night,
nights resampled 2,000 times; with the full edge, half and none.

### Results, P1 (run once as written)

[Results](outputs/parlays/results.json); recomputed with separate code:
identical.

- 2,430 qualifying legs: the model said they would hit 85% of the time; they
  hit 77.8%, about what they cost (78¢). As singles: −1.7% per dollar (t −1.5).
- **Nightly 2-leg parlay** (151 nights): model 87%, price 75.4%, hit 72.2%;
  **−7.0% per dollar** (t −1.5). The same legs as singles: −2.7%.
- **Nightly 3-leg parlay** (127 nights): model 79%, price 63%, hit 59.8%;
  **−9.8% per dollar** (t −1.4). The same legs as singles: −2.4%.
- Every 2-leg and 3-leg combination: −3.9% and −5.9% per dollar.
- Both fail. The model is overconfident exactly where it disagrees most with
  the market, and a parlay multiplies that. These are best-case prices (no
  combo margin).
- Same-game pairs (reported): two legs of the same player hit together a bit
  more often than their probabilities imply (residual covariance +0.004,
  t 4.5, 16,839 pairs); teammates and opponents show nothing (t 0.6, 0.3).

### Test P3, Kalshi's own NBA combos (fixed before their prices are downloaded)

Kalshi sells same-game parlays as combo markets (series KXMVENBASINGLEGAME;
quoted on request by market makers). The probe found them public, with each
combo's legs, result and trade prints.

- **Sample:** settled combos (yes or no) from the 2025-26 season and playoffs
  whose trades were downloaded (a fixed random sample of the traded ones).
- **Question:** do combo takers overpay? For each trade, the taker's side
  (yes or no) and price; return per dollar = payout / price − 1, before fees.
  Primary measure: dollar-weighted return of takers, t clustered by game.
  Takers overpay if it is negative with t ≤ −2.0, in both halves of the
  season (before and from 2026-02-01).
- **Reported:** by number of legs and by side; and the quoted price against
  the product of the legs' prices (for legs in the four prop series, from the
  hourly candle at or before the trade), which is the margin the quote adds.

## 2026-10-15: Where the resting-order profit comes from (decomposition, in-sample)

Same 2025-26 data as idea 1, no new rules; this is diagnosis, not a test
(`outputs/decompose/`). Resting "no" orders on every line (one cent inside
the ask, up to tip-off), with and without the model veto, and the mirror
"yes" orders.

- **The market mid is not biased.** At tip-off the mid averaged 44.3% and
  "yes" happened 45.6%; by price decile the mid is calibrated within about
  two points everywhere. There is no static "retail overpays for yes" in the
  mid, and no longshot premium to harvest: "no" orders made about the same
  (+1.4 to +2.4¢) at every price level from 10¢ to 90¢, and the lines far
  above a player's average (+2.7¢) were only a little better than the rest.
- **The flow is asymmetric.** Resting "no" orders made +1.65¢ (33,475 fills,
  t 4.1) with no model at all; resting "yes" orders lost 2.0¢ (t −3.2). The
  people who hit a resting "no" (yes buyers paying near the ask) are
  uninformed; the people who hit a resting "yes" (yes sellers) are informed.
  So the edge is spread capture from one side of the book, with adverse
  selection on the other.
- **The model's job is to avoid the informed fills.** Profit rises with the
  model's edge: orders the model rated below −5¢ lost 1-2¢; from 0 to 3¢
  made +1.9¢; 3 to 10¢ made +3.4-3.6¢; above 10¢ +3.1¢. With the veto
  (edge ≥ 0) the result is +2.93¢ in both halves of the season (H1 4,287
  fills, H2 16,354), positive in all four stats (rebounds weakest, +1.6¢) and
  in every price band (+2.0 to +3.4¢). Orders two hours before tip made
  +4.5¢ (2,416 fills) against +1.4¢ at five hours.
- **Capacity is not the limit** at this bankroll: millions of contracts
  traded through these prices over the season.

Conclusion: the strategy already chosen for the paper test (sell "no" on
every line, resting inside the ask, skipping orders the model rates below
zero) is the right shape. It is a liquidity-provision strategy with a model
filter, not a forecasting one. Picking winners is not the edge; neither is
hunting outliers.

## 2026-10-16: Scaling the "no" seller (simulation, same 2025-26 orders)

Akila asked what $25,000 and several sports would do. Replays of the chosen
rule (every line, model veto) over the 184 trading days of 2025-26 with the
staking rule (1% per order, 30% per day), unfilled orders reserving capital.
"Flow share" is the fraction of the contracts that traded through our price
that we are assumed to get (the backtest assumed all of it; half is the
working assumption from here on). Other sports are simulated by gluing
together independently resampled NBA days, i.e. they assume a sport with
the same flow and edge, which is untested.

| Bankroll | Flow share | $25/100-contract order cap | End of season | Max drawdown |
|---:|---:|---|---:|---:|
| $500 | 100% | on | $3,192 | 11% |
| $500 | 50% | on | $2,635 | 12% |
| $5,000 | 50% | on | $18,174 | 9% |
| $5,000 | 50% | off | $24,236 | 10% |
| $25,000 | 50% | on | $46,364 | 5% |
| $25,000 | 50% | off | $73,356 (bootstrap median $70,236; 10th-90th $53k-$91k) | 9% |
| $25,000 | 25% | off | $57,904 | 9% |

With $25,000 the order cap binds (about $600 a night deployed), so it has to
come off, and the return per dollar falls from about 4x at $500 to about
1.9x at $25,000 at half the flow: capital stops being the constraint and
flow does. Adding sports (independent days, half the flow, no cap, $25,000):
1 sport $70k, 2 sports $88k, 3 sports $101k, 5 sports $116k median, with
the drawdown falling from 8% to 2%. Fewer sports with no cap beat more
sports with the cap. All in-sample, one season, assuming the edge holds.

## 2026-10-16: Market scan, fixed before the data is downloaded

Question: in which Kalshi sports markets does the structural edge found in
NBA props (resting "no" orders fill against uninformed "yes" buyers) also
exist? The scan needs no model; it measures the flow asymmetry alone, so a
positive result is the floor the model filter would build on.

**Markets.** Every Kalshi series in the Sports category, excluding combo
(multivariate) series. From each series' settled markets of the last 400
days, a random sample (seed 0) of up to 1,200 that traded and settled yes
or no. Series whose first page of settled markets shows under $20,000 of
volume are skipped. NBA props are included as the control: the scan's
numbers for them should agree in sign with idea 1.

**Generic timing** (there is no tip-off time for most sports): hourly
candles ending between 7 and 4 hours before the market's expected
expiration (a game lasts about three hours, so this is pre-game for the
major sports; markets that expire long after the event, such as season-long
or multi-day ones, are reported but flagged). At each candle with a
two-sided quote, a resting "no" order one cent inside the ask (at the bid
when the spread is one cent) rests for one hour and fills from the trade
prints with the price-priority rules of `kalshi/maker.py`. The mirror
"yes" order is run the same way. One order per market per hour.

**Measures per series:** fills, contracts traded through, profit per filled
contract after the maker fee (25% of 0.07 x P x (1 - P)) and its t with
standard errors clustered by event (game); the same for "yes" orders;
fill rate; median spread; volume of the sample. Plus profit per contract
for the first and second half of each series' sample dates.

**Pass, per series:** "no" orders positive with t ≥ 2.0 and positive in
both halves, and "yes" orders not significantly positive (that would mean
the flow is two-sided and the "no" edge is spread capture a model could
also get on the yes side). Passing series are candidates for a model and a
pre-registered test of their own; nothing is traded from this scan.

## 2026-10-16: Results: market scan and Kalshi NBA combos

### Market scan (run once as written; [results](outputs/scan/results.json), [table](outputs/scan/table.csv))

The listing found 3,972 sports series, 2,270 with at least $20,000 on their
first page. The six shards scanned 274 of them in the time allowed, taken in
order of volume, so the big markets are covered and the long tail is not.

- **Control:** NBA points (1,200-market sample) gave "no" orders +3.0¢ with
  no model (t 1.6; the full-season figure was +1.65¢ for all four stats);
  "yes" orders −2.6¢. Same sign as idea 1. The other three NBA prop series
  were not reached.
- **Game-winner markets lose.** Of 83 "...GAME" series, "no" orders lost in
  most of the large ones: NFL −4.8¢ (t −2.4), MLB −7.9¢ (t −3.0), NBA −1.7¢,
  Liga MX −3.6¢ (t −3.3). As expected: both sides are a team, the flow is
  two-sided and the sharps are there. The same for NBA spreads (−3.9¢,
  t −2.1) and team totals.
- **Ten series passed** (t ≥ 2, both halves positive, "yes" not positive):
  ITF tennis match winners (+4.6¢, t 2.5, $117M sample volume), NCAA women's
  basketball games (+2.9¢, t 2.1), World Cup first-half spreads (+4.9¢),
  NASCAR race winners (+4.0¢, t 3.6), La Liga spreads (+4.3¢), World Cup
  shots on target (+6.3¢, t 3.1), **NFL anytime touchdown (+3.0¢, t 2.2,
  "yes" −1.1¢)**, WNBA first-half totals (+8.8¢), Liga MX spreads (+4.7¢),
  World Cup assists (+3.7¢). Near misses with the same shape: NFL receiving
  yards (+4.8¢, t 1.7), NCAA men's totals and spreads, WTA matches (+3.9¢,
  t 1.9, $750M volume), Ligue 1 games (+2.8¢, t 2.0 but "yes" also moved).
- **Caution.** 274 series were tested; at the 2.0 threshold about six would
  pass by chance. The ones to believe are those where "yes" orders also lost
  clearly (ITF, NASCAR, shots on target, WNBA 1H totals, Liga MX spreads) and
  the player props, where the mechanism is the same as NBA's (NFL anytime
  TD, receiving yards). Several passing markets are long-shot fields (NASCAR
  winners, ITF upsets): there the "no" edge is the favourite-longshot bias,
  not spread capture, and it comes with rare large losses.

Overall across the 274 series, resting "no" made +0.2¢ at the median and
"yes" lost 1.3¢ (fill-weighted). The asymmetry is general; the size is
market-specific.

### Kalshi NBA same-game combos (P3, run once; [results](outputs/parlays/combos.json))

236,239 combos listed for 2025-26; trades downloaded for a 29,934-combo
sample ($1.43M paid, 598 games). Takers were "yes" buyers 98% of the time.

- Takers paid an average 19¢ per contract and 17.3% of contracts paid out:
  **−9.0% per dollar (t −2.5)**. First half −10.2%, second half +2.1% (the
  playoffs; the pre-registered "both halves" criterion fails).
- By legs: 2 legs −4.5%, 3 legs −9.6%, 4 legs −16.4%, 5+ legs −18.7%
  (t −2.3). The loss grows with the number of legs, like sportsbook parlays.
- Quotes are 1.5x the product of the legs' mids (17¢ against 11¢), but the
  legs are positively correlated and 16% hit, so the quoting margin is
  roughly 1 to 3¢ per contract, not 6¢. The makers' profit is mostly the
  longshot premium on many-leg combos.

Being the combo quoter would be the largest edge per dollar seen in this
project, and it is only available through Kalshi's RFQ market-maker API,
which needs onboarding, quoting software and capital for many simultaneous
positions. Noted, not pursued at $500.

### Paper tests in the scanned markets (live from 2026-10-16)

Five of the passing or near-passing series that are in season now run the
scan's model-free rule as live paper tests, each from its own $500
(`kalshi/paper_markets.py`, every three hours): ITF men's tennis, NASCAR
race winners, Liga MX and La Liga spreads, and NFL anytime touchdown. The
rule is as scanned (orders 4 to 10 hours before expected expiration, one
cent inside the ask, cancelled at the next run or three hours before
expiration). The first run posted 33 ITF orders. These exist to check the
scan out of sample; the NFL anytime-touchdown market is also the first
candidate for a model filter (the NFL model). What $500 would have made on
the scan's own sample (half the flow, in-sample, 4 to 11 months of data):
ITF $740, NASCAR $749, Liga MX spreads $715, La Liga spreads $647, NFL
anytime TD $754, NCAA women's games $1,878; the six together from one $500
bankroll, $4,873 over 11 months (about $13,000 if the real flow is five
times the 1,200-market sample). Expect less: these markets were chosen for
passing.

## 2026-10-16: NFL props with the NFL model as filter, fixed before it runs

The scan's two NFL prop hits (anytime touchdown +3.0¢, receiving yards +4.8¢
model-free) get the same treatment as NBA: the "no" seller with a model veto.
The NFL model is the one from akilatrades/nfl-parlay-model, now
`markets/nfl` (walk-forward 2019-2026, calibrated within about a point over
125,803 predictions); it has never been tuned on Kalshi prices.

**Rule (ledgers `KXNFLANYTD+model` and `KXNFLRECYDS+model`, $500 each).**
Every three hours, for every open market in the series whose expected
expiration is 4 to 10 hours away with a two-sided quote: a "no" order one
cent inside the ask (at the bid when the spread is 1¢), cancelled at the next
run or three hours before expiration. **Veto:** the order is skipped when
(1 − p) − price − maker fee < 0, where p is the model's over-probability
for that player and line from the latest ladder made before the run (the
anytime-touchdown market is the 0.5 line of rushing plus receiving
touchdowns). Markets the model cannot price (no ladder row) are skipped, so
the ledger is a strict subset of the model-free one for the same series,
which keeps running alongside as the control. Sizing, fills and settlement
as in the other paper tests.

**Pass criteria, judged after the Super Bowl (2027-02-08):** profit per
filled contract above zero with game-clustered t ≥ 2.0, and the filtered
ledger's profit per contract above the model-free control's over the same
markets. Reported: the vetoed orders' profit (what the model kept us out of).

## 2026-10-16: Market scan, second pass: every Kalshi market

The first pass reached 274 of the 2,270 sports series with at least $20,000
on their first page. This pass runs the same model-free rule and pass
criteria (resting "no" one cent inside the ask, 7 to 4 hours before expected
expiration, one hour's rest, fills from trade prints; pass if "no" is
positive with t ≥ 2 in both halves and "yes" is not significantly positive)
on **every remaining series in every category** with that volume, sports
and non-sports, with 400-market samples instead of 1,200 so it finishes.
Combo (multivariate) series are excluded as before. Non-sports markets have
no game, so "7 to 4 hours before expiration" is simply a pre-close window;
long-horizon markets (futures, season winners, elections) will show up with
few quotes in that window and are reported with their counts. Results merge
into the same table; a series' newest scan wins. Same caution as before: at
t ≥ 2 about one series in forty passes by chance, so passing series are
candidates for paper tests, not conclusions.

## 2026-10-16: v2 of the "no" seller, fixed before opening night

v1 (2026-10-15) runs unchanged through the season as the reference. Each
v2 change below runs beside it as its own $500 paper ledger from opening
night, in `outputs/paper_maker/`, and is judged against v1 at the
2027-01-31 checkpoint on profit per filled contract (clustered t) and on
profit per dollar staked. A variant replaces v1 for the second half only
if it beats it on both out of sample. Evidence for each is from the
2025-26 decomposition (2026-10-15).

| Ledger | Change from v1 | Why |
|---|---|---|
| `no_seller_late` | Posted only 0.5 to 2 hours before tip-off | Orders 2 h before tip made +4.5¢ against +1.4¢ at 5 h; the last 30 minutes +7.2¢ |
| `no_seller_edge_sized` | Stake 0.5% to 1.5% of the bankroll, rising with the model's edge (full at 5¢) | Profit per contract rose from +1.9¢ (edge 0-3¢) to +3.5¢ (3-10¢) |
| `no_seller_veto2` | Skip unless the model's edge is at least 2¢ | Same gradient; trades fills for quality |
| `no_seller_stat_veto` | Rebounds need 2¢ of edge, other stats 0 | Rebounds were the weakest stat (+1.6¢ against +3-4¢) |

**Live trader (`live/nba_trade.py`), added before any real order:** fresh
exchange quotes before posting; a per-team cap ($15) beside the per-game
cap ($25) and a cap of six lines per game; players whose ESPN injury entry
changed in the last six hours, or who are Out, are skipped (the market
knows the news before the model does); realized P&L for the daily loss stop
comes from the account's settlements; after every run the ledger's resting
orders are reconciled with the exchange's and any unknown order is flagged.

**Market selection.** Winner markets come off the list when their two-week
paper tests end: ITF tennis (2026-10-30) and NASCAR (2026-10-30), unless
they are positive with t ≥ 2 by then. The edge is in prop markets ("does X
happen"); winner markets ("A beats B") lost in the scan and are losing live.

**Not yet done, needs a purchase:** a sportsbook-line veto (live odds feed,
about $40 a month). To be pre-registered when the feed is in hand.

## 2026-10-16: Raising the edge: sportsbook-line veto, early exit, faster quoting

Written before any of it runs. Profit for a resting-order seller is fills x
edge per fill x capital turns, less what informed buyers take back. One
change per term, each judged separately.

### Sportsbook-line veto (edge per fill)

The model is the bouncer that decides which "no" tickets to sell. The
sportsbooks are a better bouncer: they price every player prop with far
more information than four stat models fit on box scores. A "no" sold
where Kalshi's "yes" ask is above the books' probability of the over is
selling an overpriced ticket; one sold below it is selling a cheap ticket to
someone who may know more.

**Data.** The Odds API (paid feed, bought 2026-10-16): US books' player
points, rebounds, assists and threes lines, main and alternate. Book
probability of the over at a line = the average, across books quoting both
sides of that exact line, of the over's implied probability with the vig
removed proportionally. A Kalshi line with no book quote has no book
probability and is left to the model.

**Historical test, run first.** From the 2025-26 "no" seller's 33,475
fills (`outputs/decompose/orders_no.csv.gz`, orders posted 5 h and 2 h
before tip-off), a random sample of 150 games, stratified by month (seed
20261016, chosen before fetching). For each, the books' lines at the moment
the order was posted (the feed's snapshot at or just before `end_ts`).
Reported, in cents per filled contract with game-clustered t:

1. all fills in the sample (the baseline, to compare with the season's 1.65¢);
2. fills with a book quote at the exact line (coverage, and whether covered
   lines differ from uncovered ones);
3. **the veto**: covered fills where (1 - p_book) - no price - maker fee ≥ 0;
   and the fills it removes;
4. the veto at a 2¢ margin;
5. the model veto on the same covered fills, for comparison;
6. both vetoes together.

**Pass:** (3) beats (2) by at least 1¢ per contract with the difference's
clustered t ≥ 2, on a sample of at least 2,000 covered fills. If it passes,
`no_seller_bookline` runs as the live trader's rule from opening night;
if not, the trader keeps v1 and the book line runs as a paper ledger only.
About 12,000 of the feed's 100,000 monthly credits.

**Paper ledger `no_seller_bookline`,** from opening night, $500, beside the
others: v1's rule with the book veto on covered lines and the model veto on
uncovered ones. Book lines are logged every two hours in NBA hours
(`outputs/books/`), so the test can be re-run on this season's quotes.

### Early exit (capital turns)

A "no" held to settlement ties up its cost for hours and carries the
game's variance. Rule, live only: when the exchange's "yes" ask has fallen
at least 6¢ below the level we sold at (so the "no" we hold is worth at
least 6¢ more than we paid), rest a sell order for the position 1¢ inside
the "no" bid, post-only, expiring at tip-off. Judged on the exits ledger
(`outputs/live/exits.csv`): realized exit profit against what the same
contracts would have made held to settlement, over the first 200 exits.
The 6¢ threshold is roughly three times the round-trip maker fee at the
mid; it was not fitted to anything.

### Protecting the edge (adverse selection)

- The server quotes every minute instead of every five; the first order at
  a price level fills first, and a quote that is a minute stale is less
  likely to be the one a sharp sweeps.
- Resting orders on a player whose injury-report entry changed since the
  order was placed, or who is now Out or Doubtful, are cancelled on the
  next run, not just skipped for new orders. Logged with the reason.
- No new order inside 15 minutes of tip-off (v1's window already stops at
  30 minutes; this is a hard floor for every rule).

These are protective, not profit rules; their effect shows up as the gap
between paper fills (which assume we get every print through our price)
and real fills. Reported monthly: real fill rate against the paper ledger's,
and realized cents per contract against the paper ledger's over the same
markets.

### NFL props in the live trader (added 2026-10-16, before any order)

The trader also runs on NFL anytime-touchdown and receiving-yards markets
(`TRADE_MARKET=nfl`, `live/nfl_trade.py`), from Sunday 2026-10-18, dry run.
Same rule and risk limits as NBA; one account, so the open-exposure cap
counts both markets' ledgers. Orders rest 2 to 6 hours before kickoff
(kickoff from the market's occurrence time) and expire at kickoff, the NBA
window rather than the scan's "7 to 4 hours before expiration", since the
scan's expiration for these markets is two days after the game. Vetoes: the
NFL model where its ladder prices the line; the books' receiving-yards
consensus where they quote it; anytime touchdown has no two-sided book
quote and keeps the model veto only. A market with neither probability gets
no order. Evidence is thinner than NBA's (anytime TD +3.0¢, t 2.2, 2,255
scan fills; receiving yards +4.8¢, t 1.7, 769): NFL stays in dry run until
its paper ledgers (`outputs/paper_markets/`, from 2026-10-16) are positive
with t ≥ 2, and any real stake is a minority of the bankroll beside NBA.

## 2026-10-16: Stake size at a small bankroll (replay, same 2025-26 orders)

Akila asked whether 2-3% a line instead of 1% raises the return from $250.
Replays with `research/scaling.py` (every line, model veto, half the flow,
$25/100-contract order cap, bootstrap over days) say the per-line stake is
not the constraint: a night has about 175 orders (median), so 1% each asks
for 175% of the bankroll and the **30% daily cap** is what binds. Raising
the stake to 2-5% at the same daily cap leaves the season's end within
noise ($250 -> about $1,600-2,500 median) and concentrates the same 30% in
fewer lines. The lever is the daily cap, with a per-game cap to spread it:

| Start | Stake | Day cap | Game cap | Boot median | 10th | P(loss) | Median max DD |
|---:|---:|---:|---:|---:|---:|---:|---:|
| $250 | 1% | 30% | 10% | $1,643 | $875 | 0% | 24% |
| $250 | 2% | 50% | 15% | $2,106 | $981 | 0% | 38% |
| $250 | 3% | 70% | 20% | $2,998 | $1,097 | 0% | 46% |
| $250 | 3% | 100% | 25% | $7,209 | $2,151 | 0% | 45% |
| $500 | 1% | 30% | 10% | $2,732 | $1,733 | 0% | 21% |
| $500 | 3% | 100% | 25% | $11,122 | $4,433 | 0% | 36% |

Stress, $250, shrinking every fill's profit toward zero edge:

| Edge | 1% / 30% day: median, P(loss), P(< half) | 3% / 100% day: median, P(loss), P(< half) |
|---|---|---|
| As backtested (3.1¢) | $1,777, 0%, 0% | $7,246, 0%, 0% |
| Halved (1.6¢) | $778, 3%, 0% | $1,346, 13%, 5% |
| None | $265, 42%, 8% | $82, 67%, 57% |

Reading: the aggressive setting roughly quadruples the median if the edge
is as backtested, and loses more than half the money in a majority of
seasons if there is no edge. The conservative setting is nearly flat with
no edge. Since the first weeks are exactly the test of whether the edge
survives real fills, the trader keeps 1% / 30% / per-game cap until the
realized cents per contract over the first 500 fills are positive with
t ≥ 2; the daily cap then rises in steps (50%, 70%), never above 70%, and
only while the running realized edge stays above 1.5¢. Written here before
the first fill. The replay's drawdowns (21-46%) are larger than the
2026-10-16 scaling entry's (5-12%), which sized edge-first within a day
without a per-game cap and measured drawdown differently; these are the
numbers to plan around.

### Result: sportsbook-line veto, historical test (run 2026-10-16 19:19 UTC)

151 games sampled, all found in the feed; 4,862 fills; a book quote at the
exact line for 66% of them (3,197). Cents per filled contract, game-clustered t:

| Fills | Count | ¢/contract | t |
|---|---:|---:|---:|
| All in the sample | 4,862 | +2.04 | 1.8 |
| Covered by a book quote | 3,197 | +2.15 | 1.6 |
| **Book veto (book edge ≥ 0)** | 1,647 | **+3.81** | **2.4** |
| Removed by the book veto | 1,550 | +0.38 | 0.3 |
| Book veto at 2¢ | 476 | +2.23 | 1.0 |
| Model veto, same covered fills | 2,074 | +2.69 | 1.6 |
| Both vetoes | 1,149 | +3.74 | 1.9 |

Kept minus removed: +3.44¢, t 2.42. Gain over all covered fills +1.66¢.
**Passes the pre-registered test** (≥ 1¢, t ≥ 2, ≥ 2,000 covered fills).
The books are better calibrated than Kalshi's ask at every decile (table in
`outputs/bookline/summary.md`); the 2¢ margin removes too much. Per the
pre-registration, `no_seller_bookline` is the live trader's default rule
from opening night (`TRADE_RULE`), with the model veto on uncovered lines.
Caveats: 150 games, one season, and the fills the veto removes were still
slightly positive, so the gain is in selection, not in avoiding losses; the
paper ledger beside v1 is the out-of-sample test.

## 2026-10-16: Market scan, second pass: results

All 20 shards finished 22:16 UTC. Both passes together: 5,393 series listed,
1,178 with enough trading in the window to test, **70 pass** (positive "no"
seller with t ≥ 2 in both halves, "yes" not significantly positive). At one
in forty by chance, about 30 of the 70 are noise, and 45 of the 70 have
fewer than 100 fills. Full table: `outputs/scan/table.csv`.

**Non-sports: no edge.** Commodities (10 series, 2,226 fills) −0.6¢;
financials (S&P ranges) −1.1¢; crypto, economics, elections, politics and
entertainment have no series with 100 fills that passes. The exception is
the **Mentions** markets (will X be said): 3 series, 1,398 fills, +3.6¢;
NCAA Mention +6.5¢ (t 2.3, 813 fills). A market with a fan on the "yes"
side; the rest have none. The hope that price markets (crypto, equities)
would fill NBA's dark days is not supported.

**Scorer props: flat.** NHL goalscorer +0.1¢ (180 fills), NFL passing
touchdowns −4.2¢ (334), NHL first goal +4.7¢ and points +6.2¢ on 62 and 143
fills. Not a second NBA.

**Passes with at least 100 fills, prop-shaped, in season or soon:**

| Series | Fills | ¢ | t | Halves | Season |
|---|---:|---:|---:|---|---|
| KXCLUBFBTTS, club soccer both teams to score | 567 | +11.5 | 3.4 | +13.0 / +10.2 | now, daily |
| KXNCAAMB1HSPREAD, college basketball 1H spread | 223 | +16.4 | 4.0 | +20.2 / +13.7 | from Nov |
| KXUCLCORNERS, Champions League corners | 141 | +29.4 | 3.1 | +26.1 / +31.8 | Tue/Wed |
| KXUFCMOF, UFC method of finish | 218 | +8.6 | 2.3 | +6.8 / +10.4 | Saturdays |
| KXNBAFTM, NBA free throws made | 127 | +12.4 | 2.1 | +18.7 / +9.6 | from Oct 20 |
| KXNCAAMENTION, NCAA broadcast mentions | 813 | +6.5 | 2.3 | +2.7 / +10.0 | now |
| KXWNBA1QSPREAD / KXWNBA1HTOTAL | 109 / 675 | +16.4 / +8.8 | 2.7 / 2.6 | both + | summer |

Winner-shaped passes (NWSL spread, NCAAW, AHL, VTB, Rocket League, EWSL,
NASCAR, ITF) are noted and not tested further: winner markets lost in the
first pass and are losing live.

**Pre-registered paper tests, from 2026-10-17:** model-free "no" seller
ledgers ($500 each, same rule, window and fills as the others) for the six
in-season rows above: BTTS, UCL corners, UFC method of finish, NBA free
throws made, NCAA Mention and, from the first game in November, NCAA 1H
spreads. Judged after 2026-12-15 (or 300 fills, whichever is later): kept if
positive with t ≥ 2; otherwise off the list. Expected by chance: about one
of the six passes anyway, so a single survivor is weak evidence; two or more
is not. Grouped reading, written before the data: the mechanism is a fan
backing a person or an event to *happen*; BTTS, corners, free throws and
mentions fit; a 1H spread is half-way to a winner market.

## 2026-10-16: Execution studies (from the research agenda), written before running

Akila's research agenda (strategy_research.pdf) puts execution first: whether
the "no" seller's fills are the ones a sharp sweeps. Two offline studies on
the 2025-26 NBA fills and trade prints; no change to the running ledgers or
the trader.

**Markouts and a toxicity veto (`research/markouts.py`).** For each paper
fill, the first print at or through our level is the fill; markouts are
the last "yes" price 5, 15 and 60 minutes after it and at the last print
before tip, from our side (positive = price moved our way). Features known
before posting: the yes price change in the prior hour, prints and
yes-taker share in the prior 15 minutes, volume so far. Splits at each
feature's median, plus two flags fixed now: **toxic** = prior-hour momentum
above +2¢, or yes-taker share above 80% on at least 3 prints; **late** =
filled within 15 minutes of tip. Endpoint: settlement profit per contract
(clustered t) in each split; markouts are diagnostics, not the endpoint.
Reading, in advance: if the toxic group's settlement profit is below the
rest by ≥ 1.5¢ with the difference's t ≥ 2, a pre-posting veto goes into
the v2 paper ledgers (not the trader) as `no_seller_toxveto`. If the
groups do not differ, the fills are not being picked off in a way these
features see, which is good news for execution.

**Quote placement (`research/quote_placement.py`).** Same orders, same
prints, four price policies: join the no bid; improve 1¢ (the current
rule); improve 2¢ when the spread allows; improve 1¢ only when the
model's edge at that price is at least 2¢. Endpoint: net profit per 100
eligible orders (unfilled orders count zero), not per fill, so a policy
cannot win by filling less. Also reported: fill rate and per-fill profit.
Expected in advance: joining the bid fills less and earns more per fill;
2¢ fills more and earns less; which wins per 100 orders is the question.

### Results: execution studies (run 2026-10-16, offline)

**Markouts.** All 33,475 paper fills matched to the print that filled them.
Settlement profit +1.65¢ (t 4.1); markouts from our side −1.16¢ at 5
minutes, −0.98¢ at 15, −0.91¢ at 60 and −0.94¢ at the last pre-tip print.
So after we are filled the "yes" price drifts about 1¢ *against* us and
stays there, yet the position still settles +1.65¢: the market's "yes"
stays overpriced relative to outcomes all the way to tip. Two readings
follow. (1) There is mild adverse selection in the price, but the edge is
in settlement, not in the mark: an exit rule that sells back on price
moves would give the edge away, and the pre-registered 6¢ early exit will
rarely trigger. The exits ledger stays, judged on realized exits against
hold value as written. (2) None of the pre-posting features separate good
fills from bad: the **toxic** flag (1,167 fills) made +2.96¢ against
+1.61¢ for the rest, the wrong direction for a veto; fills in the last 15
minutes before tip made +3.29¢ (t 3.2) against +1.56¢ earlier; large
prints that filled us made +1.51¢ against +1.80¢ for small ones (not
significant). **The pre-registered veto criterion (toxic group worse by ≥
1.5¢, t ≥ 2) is not met; no toxicity veto.** Most orders have no prints in
the hour before posting (median momentum and 15-minute print count both 0):
these markets are thin before tip, which is itself why resting orders work.

**Quote placement** (35,404 eligible orders, model veto on, one contract
each):

| Policy | Fill rate | ¢ per 100 eligible orders | t | ¢ per filled contract |
|---|---:|---:|---:|---:|
| Join the no bid | 30% | +86 | 4.7 | +2.86 |
| **Improve 1¢ (current rule)** | 58% | **+171** | 6.1 | +2.94 |
| Improve 2¢ when the spread allows | 68% | +168 | 5.5 | +2.47 |
| Improve 1¢ only with model edge ≥ 2¢ | 58% | +191 (on 28,213 orders) | 6.2 | +3.30 |

Joining the queue halves the fills and the profit; 2¢ inside buys 10
points of fill rate and gives it all back in edge; the 1¢ rule is at the
optimum of the three price policies. The edge-2¢ filter earns more per
order on fewer orders (total +540 against +605 for all orders at 1¢), so
it is the better rule when the daily cap, not the opportunity set, binds,
which is the small-bankroll case; it is already running as
`no_seller_veto2`. No change to the trader from this study.

## 2026-10-17: Desk studies, written before running (`research/desk.py`)

Four replays on the 2025-26 NBA "no" seller (model veto on, half the flow,
$500, 1% a line, 30% a night, 10% a game), offline, nothing live changes.

1. **Value per quote.** A logistic fill model from what is known at posting
   (spread, no price, open interest, the hour's volume, hours to tip), fit
   on the first half of the season and scored on the second. On the second
   half, the daily cap is spent by three rankings: model edge (the current
   rule), P(fill) × edge, and P(fill) × edge per dollar-hour reserved, plus a
   random-order control. Endpoint: season end from $500 and profit per 100
   orders placed. Adopted into the v2 ledgers only if the EV ranking beats
   edge-first by ≥ 10% of end bankroll on the holdout half.
2. **Inventory.** Nightly paper profit per fill against that night's
   league-wide scoring surprise (points per game minus the trailing-20-night
   mean). Pre-registered reading: a correlation below −0.3 means a night of
   "no" fills is one short-scoring position and a game-total hedge is worth
   testing; above −0.15, the per-game caps already handle it.
3. **Sizing under uncertainty.** Daily cap = 30% × (shrunk running edge / 3¢),
   clamped to 10–70%, where the running edge is the mean profit per contract
   of fills so far shrunk toward zero by 250, 500 or 1,000 imaginary
   zero-edge fills. Compared with the fixed 30% cap on the backtested edge,
   a halved edge and no edge. Adopted if it ends higher at the full edge and
   loses less with no edge.
4. **Attribution.** On the 3,197 fills with a book quote: profit = premium
   (what selling above the books' probability is worth, after fee) +
   residual. Reading: a residual near zero means the edge is the liquidity
   premium and the levers are breadth and speed; a residual with t ≥ 2 means
   there is selection skill beyond the books.

### Results: desk studies (run 2026-10-17, offline)

**1. Value per quote: not adopted.** The fill model is well calibrated on
the holdout (predicted 0.29→0.88 by decile against actual 0.30→0.77; spread
and price level do the work, open interest and hours a little). Ranking the
daily cap by P(fill) × edge per dollar-hour ended the holdout half at
$1,566 against $1,161 for edge-first, which clears the pre-registered 10%,
but the gain does not survive inspection: most of it is the hours term
preferring the 2-hour postings over the 5-hour ones (the known late-posting
result, already running as `no_seller_late`), and within a single posting
time the holdout half is the one stretch where edge-first ranking did badly
(random order beat it, $1,064 to $885) while over the first half and the
whole season edge-first beat random ($2,680 to $1,656). A ranking that wins
only on the half it was not fit on, and loses on the other, is noise. The
fill model itself is kept (`research/desk.py`) for the capacity study once
real fills exist.

**2. Inventory: no hedge.** Correlation of nightly profit per fill with the
night's scoring surprise is −0.06 (178 nights); high-scoring nights made
$0.76 per fill against $1.57 on low-scoring ones, a tilt but a weak one.
Below the pre-registered −0.15 line: the per-game and per-team caps are
enough. No game-total hedge.

**3. Adaptive sizing: not adopted as the default, kept as the insurance
option.** Fixed 30% cap: $500 → $1,849 at the full edge, $759 at half,
**$190 with no edge** (74% drawdown). Shrunk-Kelly cap (10–70%, prior 500
zero-edge fills): $1,330 at the full edge, $885 at half, **$635 with no
edge** (31% drawdown). It gives up 28% of the upside for three times the
capital preserved if the edge is not there, because it sits at the 10%
floor for the first month while the running estimate is still near zero.
The pre-registered rule (higher at full edge and safer with none) is not
met, so the fixed cap with the written step-up schedule stays; the adaptive
cap is the right choice for anyone who weights "the edge is gone" more
heavily than the backtest does, and is documented for that.

**4. Attribution: the premium is shared with the books.** On the 3,197
fills with a book quote, our price sat on average only 0.14¢ above the
books' probability; the 2.15¢ of profit is 2.01¢ residual (t 1.5): on
these lines the over came in below *both* Kalshi's price and the books'.
Reading: sportsbooks shade player props toward the over as well (they
carry the same public), so "sold above the books" is a selection signal
rather than the source of the edge; the source is the public's
over-optimism, which both venues price in. Consequence: the book veto
works by picking lines, not by arbitraging the books, and the gross edge
against the books is itself positive but not yet significant (t 1.5).

## 2026-10-17: Model refresh study, fixed before it runs

Prompted by the question of which of the standard quant toolkit the model
uses. Stochastic calculus and differential equations are not tested: the
contract is a binary held to settlement with no hedge, so there is no price
process to solve. Four things that could plausibly help are tested offline
against the frozen model (`research/model_refresh.py`), on the 2025-26
holdout only, with the same walk-forward as the backtest (refit before each
month on earlier games). Nothing is tuned on the holdout; every setting
below is written here first.

**Mean-model variants** (the spread layer is unchanged):

1. `control`: the frozen Poisson regression.
2. `gbm`: gradient-boosted trees with a Poisson loss on the same feature
   matrix and the same season weights. Settings fixed now: 300 rounds,
   learning rate 0.05, 15 leaves, 50 rows per leaf, L2 = 1.0. No tuning.
3. `hier`: the Poisson regression plus a player random effect, Gamma-Poisson
   partial pooling: each player's factor is (his actual + a) / (his expected
   + a) over his training games in the latest two seasons, so a player with
   little history stays at the regression and a player with a long
   consistent residual moves off it. The prior strength `a` is chosen from
   {10, 30, 100, 300} by log loss on the last training month only (never
   the test month).
4. `iso`: the control's probabilities passed through an isotonic
   calibrator fitted, per stat, on every earlier out-of-sample prediction
   (the 2021-22 to 2024-25 development predictions plus earlier holdout
   months).

**Judged on**, in order: (a) log loss over every player-game-line in the
holdout; (b) the veto replayed on the season's 53,549 resting "no" orders,
each variant's probability recomputing the edge and each order's
place/skip, scored as profit per 100 eligible orders with one contract per
order (unfilled orders count zero), with the difference from the control
given a game-clustered t. A variant is adopted only if (a) improves and (b)
improves with t ≥ 2; otherwise the control stays.

**Portfolio allocation**: in the bankroll replay from the desk study
(30% daily cap, 1% stake, 10% game cap), order the day's candidates by
edge ÷ standard deviation of the contract (√(p(1−p)), with within-game
correlation taken as the −0.06 measured in the inventory study, i.e. close
to independent) instead of by edge. Judged on the whole season and on each
half separately, against edge-first and random order. Adopted only if it
beats edge-first on both halves by 10% or more, the same bar the EV-ranking
study failed.

Expected: small log-loss gains at most from `gbm` and `hier`; `iso` close
to nothing because the control is already calibrated to within half a
point per decile; the portfolio ordering close to random because the
correlations are near zero.

### Results: model refresh (run 2026-10-17, offline; `outputs/model_refresh/`)

535,731 player-game-lines and all 53,549 resting orders of 2025-26
re-priced by each variant. **Nothing adopted; the frozen model stays.**

| Variant | Log loss (vs control, t) | Veto: profit per 100 quoted orders (diff vs control, t) |
|---|---|---|
| control | 0.30380 | +112.9¢ |
| gbm | 0.30247 (−0.0013, t −5.8) | +107.9¢ (−5.0, t −0.6) |
| hier | 0.30413 (+0.0003, t 3.1) | +122.4¢ (+9.5, t 1.6) |
| iso | 0.30387 (+0.0001, t 1.8) | +113.2¢ (+0.3, t 0.1) |

- **Gradient boosting** is the better forecaster (0.4% lower log loss, a
  clear t of −5.8 over 536k lines) and makes *less* money as a veto. The
  two judgments disagree, so the pre-registered rule (both must improve)
  says no. Reading: the veto's job is to skip the lines where the public
  is right, and a sharper mean does not change which lines those are; the
  trees mostly reshuffle probabilities inside the band the veto already
  keeps.
- **Hierarchical player factor** goes the other way: slightly worse log
  loss (the nested selection picked the strongest prior, 300, in 27 of 36
  stat-months, i.e. the data asked for almost no player effect beyond the
  regression's own shrunk rates) and a +9.5¢ veto gain at t 1.6, short of
  the bar. Noted as the one candidate worth a second look next season with
  fresh orders; not adopted now.
- **Isotonic calibration** does nothing, as expected: the control is
  already calibrated.
- **Portfolio ordering (edge ÷ sd)**: $1,569 against $1,849 for edge-first
  over the season, and it loses the second half ($783 vs $1,161). Fails the
  bar. A side finding: random order, across six seeds, ends anywhere from
  $722 to $3,541 from the same orders, so the $500 compounding replay is
  far too path-dependent to rank orderings on; the per-100-orders metric
  (edge-first +21.8¢, edge/sd +16.9¢) is the one to read, and it also says
  no. Orders in the top edge quintile (cheap "no", average price 9.5¢) fill
  only 36% of the time against 70% in the middle quintile; a fill-aware
  ordering was the desk study's EV-ranking variant and was not robust.

Consequence: the mean model is not the bottleneck. The edge is in which
lines get quoted (the sportsbook veto) and in getting real fills, which is
where the next effort goes. `control_matches_frozen_rule` = 1.0: the
control's recomputed decisions reproduce the frozen ledger exactly.

## 2026-10-17: Targeted scan of the series the second pass ran out of time on

608 sports series (first-page volume $582M) were never scanned because their
shards hit the five-hour budget. `research/scan_markets.py` now takes
`--series` (and the workflow an input) to scan a named list. Two targeted
runs today, same rules as the second pass (400-market sample, resting "no"
one cent inside the ask, pass = t ≥ 2, both halves positive, "yes" side not
also passing):

**Goalscorer family.** EPL Goalscorer: 10 "no" fills in 400 markets
(+6.1¢, t 0.4). UCL Goalscorer: 41 fills, −8.3¢. UEFA Nations League Goal:
no two-sided quotes at all. EPL Corners: 39 fills, +10.9¢, second half
negative. Reading: soccer player markets on Kalshi are one-sided or empty
before kickoff; there is no crowd to rest against. Not a business today;
re-scan if soccer liquidity grows.

**Prop-like series.** 28 scanned. One pass: **KXNBA3D, NBA player
triple-double: 509 fills, +4.47¢, t 2.25, first half +6.2¢, second half
+2.8¢, "yes" side −11.2¢ (t −2.5)**, the thesis shape exactly (fans buy the
triple-double). Added to the paper ledger, judged 2026-12-15 or at 300
fills like the other candidates. Near misses, not added: NBA blocks (216
fills, +2.0¢, t 0.5, first half negative), WNBA assists (+1.8¢, t 0.4),
UCL both-teams-to-score (+1.4¢, t 0.4). Negative or flat: WNBA points
(−3.4¢) and rebounds (−4.0¢), NFL receptions (−1.1¢, 120 fills), MLB
hits+runs+RBIs (−2.0¢), golf head-to-head (−0.1¢), LoL games (−3.2¢). No
two-sided quotes before kickoff (0 fills in 400 markets): NFL rushing
attempts, fantasy points, longest rush, first team touchdown, NHL saves;
the receiving-yards escalators and ladders returned no settled markets.

Reading across both runs: the breadth that exists is NBA (a fifth NBA
market, same players and nights as the current edge). Most NFL player
props on Kalshi are not quoted two-sided pre-game, so a resting order never
fills there, whatever the edge would be.

## 2026-10-17: Outside review of the repo, item by item

A reviewer's five suggestions, checked against what the record already
holds and, where new, tested the same day (offline, no live change).

1. **Tennis: skip cheap "no".** New ledger. On the scan's own 2025-26 ITF
   orders (2,409 "no" orders, 1,180 fills, April–August), "no" at 30¢ or
   more made +6.4¢ per fill (t 2.7) against +1.7¢ (t 0.7) below 30¢; the
   reviewer's 40¢ cut separates less (+5.0¢ vs +4.4¢). The live ledger's
   first 64 fills lost everything below 30¢ (0 of 22). A second tennis
   ledger, `KXITFMATCH+no30` (same rule, "no" price ≥ 0.30), runs from
   today beside the unfiltered control, one $500 paper bankroll each,
   judged on new fills only at the same 2026-10-30 date. Stated plainly:
   the 30¢ line was chosen with both the historical and the first live
   fills in view, which is why it gets a new ledger rather than replacing
   the control. Not applied to NBA.
2. **Sportsbook veto timing and matching.** Already as the reviewer asks:
   `research/bookline_backtest.py` requests the historical odds snapshot at
   the order's posting time (`end_ts`, five hours before tip for most),
   never later, and matches events by both teams with a start within three
   hours. The residual risk is player-name matching across feeds
   (`normalize_name`); 1,647 of 21,373 fills had a book quote, so coverage,
   not timing, is the weakness, and more books in the consensus is the
   lever. Nothing to change.
3. **Execution: cancel after 30 minutes / only post at a bigger edge.**
   Tested now against the 2025-26 fills matched to their prints
   (`outputs/execution/markouts.csv.gz`): the median fill arrives 105
   minutes after posting. Per 100 eligible orders, hold to tip +170.8¢ (t
   6.1); cancel if unfilled after 30 min +42.6¢; 60 min +71.4¢; 120 min
   +105.5¢; 180 min +130.1¢. Early cancellation keeps the slightly better
   fills (+3.6¢ each) and throws away two thirds of them. Hold stays. The
   "only post at a comfortable edge" variant was the placement study's
   `edge2` (edge ≥ 2¢): fewer orders, less profit per 100 eligible. The
   1¢-inside placement remains the baseline, as the reviewer suggests.
4. **Hindsight in the NBA model (who actually played).** Measured on
   2026-10-15 and bounded: the maker test without the teammates-out
   features (the only features that use the box score's "did not play")
   made +3.8¢ (t 5.0) against +3.4¢ with them, so the head start is not
   where the edge comes from. The model-free rule (+1.65¢, t 4.1) uses no
   model at all and so no hindsight. The live trader reads the actual
   injury report (`cancel_on_injury`), not the box score. Nothing to change.
5. **Correlated exposure within a game.** Already in place: per-game cap
   10% of bankroll, per-team cap, daily cap 30%, and the inventory study
   (2026-10-17) measured nightly profit against the night's scoring
   surprise at −0.06 (178 nights), below the pre-registered line for a
   hedge. The staged 1%/30% start and the adaptive (shrunk-Kelly) cap are
   the conservative-while-unproven options already documented.

Net: one new ledger (tennis price floor), four items confirmed already
handled or tested and declined.

### Second review (same day): two points stood up, both fixed

The reviewer re-read the repo and pushed back on items 2, 4 and 5 above.
Checked against the code and data:

**2a. Per-order snapshot timing in the sportsbook backtest: the reviewer
was right.** `sample_games` took one `end_ts` per game from an arbitrary
order, and 634 of the 1,013 games have both 5-hour and 2-hour postings. In
38 of the 151 sampled games the snapshot was requested after the game's
earliest posting (up to 176 minutes after). Per order, 53 of the 3,197
covered fills were vetoed with a quote newer than their own posting.
Re-scored on the 3,144 fills whose snapshot predates their posting: kept
+3.90¢ (t 2.43), removed +0.38¢, kept-minus-removed +3.52¢ — against +3.81
/ +0.38 / +3.44 as reported. The lookahead rows themselves were −1.5¢, so
the error worked against the result, not for it. Fixed:
`sample_games` now requests the snapshot at each game's earliest posting.
The committed `book_lines.csv.gz` is from the old run; a refetch costs
~12,000 credits and is deferred, since the per-order re-score above
settles the question. Coverage numbers corrected: 4,862 sampled fills in
151 games, 3,197 with a book quote (65.8%), 1,647 kept by the veto.

**2b. Live consensus ignored the event: the reviewer was right, and this
one mattered.** `consensus()` grouped by (book, player, stat, line) with no
event key, and `attach()` matched on (player, stat, line) only. The book
log looks 36 hours ahead, so a player on a back-to-back had both games'
lines in the file and the first one won. Fixed: `consensus()` groups by
event (`event_id`, `commence_utc`) as well, `log_books.py` keeps those
columns, and `attach()` matches on the Eastern game day when both sides
carry a time (falls back to the old match otherwise). Unit-checked on a
two-game case. The NBA book log is empty until the season starts, so no
live decision was affected; the NFL log was one game per player.

**4. Closing lines in the model features: correct as stated, left as a
known limit.** `implied_points` and `team_spread` come from the closing
line, which a 5-hours-before order could not see. The move from opening to
close is small for NBA sides and totals and enters only through the model
veto (the model-free rule, +1.65¢, uses no line). Recorded; a point-in-time
line history would be needed to remove it, and we do not have one.

**5. Within-game correlation measured directly, as asked.** On the 20,641
model-veto fills, standardised against the market-implied probability:
intraclass correlation within a game +0.029 (21 fills per game on
average, variance inflation 1.57×), within a team-game +0.032, within a
player-game +0.067 (4.9 fills), within a night +0.018 (113 fills,
inflation 3.05×). Small per pair, material in aggregate, which is exactly
what clustering is for: the headline t is 9.7 if fills were independent,
6.1 clustered by game, 6.5 clustered by night. The −0.06 figure in the
inventory study was a different quantity (nightly profit against the
night's scoring surprise) and is no longer cited as evidence of
independent positions. The live limits ($25 per game, $15 per team, 6
orders per game, $75 per night) already bound the within-game and
within-night exposure; the paper props ledger has only the daily cap and
is a measurement tool, not a sizing tool, so it stays as is. The $25
per-game live cap equals the replay's 10% at the $250 start and binds
harder as the bankroll grows, which is the conservative side.

Net from the two reviews: two code fixes (snapshot timing, event-aware
book matching), two corrections to how results were described (coverage
numbers, the correlation claim), no change to any rule or result.

### Third review (same day): one real bug, fixed, with tests

`consensus()` had been given `dropna=False` on its pivot; with a
multi-level index that builds the cartesian product of every key level (16
rows from 4 real ones in a two-game check, unbounded on a full slate). The
rows were discarded downstream so no probability was wrong, but the table
could have grown enough to fail the book-log workflow. Fixed: default
`dropna`, with missing event keys filled before the pivot instead. Also,
as the reviewer asked: `attach()` no longer falls back to player-only
matching when the book table carries game times and the priced frame has
no tip time; it attaches nothing. Two regression tests committed
(`tests/test_books.py`: games kept apart with only observed rows; the line
attached to its own game, and nothing attached without a tip time). The
reviewer's remaining point stands as written: +3.90¢ is a per-order
sensitivity check on the old snapshots, not a full rerun with
earliest-posting snapshots, which is deferred for its credit cost.

### Results: the last 1,017 sports series (run 2026-10-17)

Every sports series above the volume bar has now been through the scan.
Of these 1,017, 698 had too few settled markets with two-sided quotes to
test (median 15 markets; season-long futures) and 319 were testable. Nine
passed, which is about what chance alone gives at this bar (5% of 319 ≈
16), so each is read as a candidate at best:

| Series | Fills | ¢ | t | Note |
|---|---:|---:|---:|---|
| KXNASCARTOP10, driver top-10 finish | 108 | +14.1 | 3.5 | both halves +11 or more; "yes" side −14¢ (t −3.1): the prop shape (fans back a driver). **Added to the paper ledger**; three races left this season. |
| KXWNBA1QWINNER, WNBA first-quarter winner | 306 | +6.5 | 2.2 | off-season until May |
| KXINDYCARTOP10 | 208 | +9.8 | 2.1 | off-season until March |
| KXFIFAWGAME, women's international match | 159 | +5.5 | 2.1 | winner market; tennis argues against |
| KXISLGAME, Israel league match | 246 | +3.8 | 2.0 | winner market, borderline |
| KXBIG3GAME, KXCONMEBOLLIBSPREAD, KXISRPLCUPGAME, KXNHL2OT | 74, 32, 10, 5 | | | too few fills |

Near misses worth a look next season, not added: Serie A both-teams-to-score
(537 fills, +6.4¢, t 1.9), NBA points leader of the night (316, +5.3¢, t
1.8, a prop-shaped NBA market), IPL team total (145, +12.9¢, t 1.9).
Negative with volume: La Liga BTTS (644, −5.1¢), MLS BTTS flat.

Reading, across all three passes (2,075 testable sports series): the
positives that survive both halves and have a losing "yes" side are
player or driver markets (NBA props, NBA triple-double, NASCAR top-10,
World Cup score-or-assist, UFC method); game-winner and spread markets
are flat as a class. The scan is finished; no further breadth work until
the live ledger has real fills.

### Fourth review (same day): live-trader safety, five items, all changed

These concern the trading engine rather than the edge. Each was verified
against `live/nba_trade.py` as it stood, then fixed with an adversarial
test (`tests/test_nba_trade.py`, `tests/test_books.py`).

1. **Reconcile before placing (was: after).** A run that placed orders and
   crashed before writing the ledger left orders the next run's exposure
   count could not see. Now the exchange's resting orders are compared with
   the ledger *before* candidates are sized; any order on the exchange that
   the ledger does not know, or a failure to read the exchange, means
   nothing new is placed that run. Test: a stranger order on the exchange
   → zero placements, recorded in `last_run.json` under `reconcile_before`.
2. **Dry-run rows no longer block live orders.** The "already have an
   order in this market" check counted rows of any status including
   `dry`, so a dry run earlier in the day would have suppressed the live
   order for the same market after the switch. In live mode only real
   statuses count; in dry mode the old behaviour stands so dry logs are
   not duplicated. Tested both ways.
3. **Teammate injuries.** The pre-order filter now skips every candidate on
   a team where a player was newly ruled Out in the last six hours, and
   the cancel pass pulls resting orders on a team placed before a teammate
   was ruled Out (orders placed after are kept: they were priced with him
   out). If the injury feed cannot be read, nothing new is placed, instead
   of proceeding without the check. Tested.
4. **Book freshness at the books, not at download.** `consensus()` now
   carries `updated_utc`, the oldest contributing book's own last-update
   time, through the log; `attach_latest()` drops lines whose books last
   moved more than four hours ago even if the file was downloaded a minute
   ago. Tested with a fresh and a nine-hour-old line in a just-written
   file.
5. **Model age and kill-switch scope.** New orders need a projection run
   within `MAX_MODEL_AGE_HOURS` = 9 (projections every three hours to
   21:30 UTC, trader until 04:59 UTC), read from the ladder file names the
   projections workflow commits; older, or none, places nothing. The kill
   switch cancels only tickers with the strategy's prefixes (`KXNBA`,
   `KXNFL`), not other orders in the account. Both tested.

Full suite: 99 tests. Live behaviour on the server is unchanged until
projections exist (opening night); until then the trader places nothing,
which is also what the age check now guarantees.

### Fifth review (same day): three edge cases, all closed

1. **Filled-and-unrecorded orders.** Pre-trade reconciliation only compared
   *resting* orders, so an order from a crashed run that had filled
   completely was invisible to it. `reconcile()` now also reads the
   account's positions and the last three days of fills in this market's
   tickers; any ticker the ledger never ordered blocks new placements
   (`positions_not_in_ledger` in `last_run.json`). Test: a ghost position →
   zero placements.
2. **Old book logs without `updated_utc`.** `attach_latest()` now treats a
   log without the books' own update times as no book data (the model veto
   takes over) instead of silently skipping the freshness check. The
   committed `nfl_latest.csv` is in the old format until the next book run
   regenerates it; until then NFL runs are model-veto only, by design. Test
   added.
3. **Model age from a stamp, never from mtime.** `live/nba_projections.py`
   writes `outputs/projections/latest_meta.json` with `generated_utc`;
   `projection_age_hours()` reads that, else the ladder file names, and
   returns infinite (no new orders) if neither exists. The mtime fallback is
   gone, since a checkout gives an old file a fresh mtime. Test: fresh
   mtime with no stamp → infinite age.
4. **Kill switch by ownership.** Orders now carry a client_order_id tagged
   `smm-`; the kill switch cancels an order only if its id is in the ledger
   or it carries the tag, and only in the strategy's markets. A manual NBA
   order placed from a phone on the same account is left alone. Test added.

103 tests. Agreed with the reviewer's closing line: the open question is
now whether the edge survives live execution, not whether the code has an
obvious defect, and that question is answered by fills, not by review.

## 2026-10-17: Execution accuracy, measured on every real order

Prompted by an outside note on Kalshi's queue-position endpoint. Two
corrections to that note first: the trader does not run on GitHub Actions
every 15 minutes, it runs on the DigitalOcean server every minute (the
Actions workflow is the dry-run mirror), and that server is already paid
for; and a websocket feed would not make a resting order fill sooner, as
the note itself says, so it is not built.

What is built (`live/execution.py`, wired into `live/nba_trade.py`):

- **Queue position log.** Every 15 minutes, for each resting order, Kalshi's
  `GET /portfolio/orders/{id}/queue_position` (contracts ahead of us at our
  price) is appended to `<market>/queue.csv`. The first reading after
  placement is the order's starting queue.
- **Per-order execution report** (`execution.csv`, `execution.md`): minutes
  from signal to placement, starting queue, minutes to first fill,
  contracts filled against ordered, settled profit where known.

Pre-registered readings, judged at the 500-fill checkpoint:

1. *Fill capture.* The paper simulator counts an order filled when a print
   trades through its price. The real fill share on orders whose price
   traded (from the trade prints) is the capture rate; the backtest
   assumed 50% (`FLOW`). Below 25% the per-100-orders profit halves and the
   stake plan is re-run with the measured rate before any step-up.
2. *Queue and fills.* Fill probability by starting queue (0, 1–20, 21–100,
   100+ contracts ahead). If orders behind 100+ contracts rarely fill, the
   1¢ improvement is re-examined for those lines only (a pre-registered
   second placement study, not a live change).
3. *Profit of real fills.* Settled profit per real fill against the
   backtest's 2.9¢, game-clustered t, the same test as the paper ledgers.

No live rule changes from this; it is measurement.

### Execution measurement, corrected after review (same day)

Four measurement defects in the first version, all real, all fixed and
tested against the current fill shape:

1. **Capture, not fill share.** The report had filled ÷ ordered, which is
   not the 50% capture assumption the backtest makes. It now also fetches
   the public prints for each order after placement and counts the
   *qualifying volume* (takers buying "yes" at or above our level); capture
   = our fills ÷ that volume, capped at 1. Fill share of the order is kept
   as a separate column.
2. **Current fill fields.** Kalshi fills carry `count_fp`,
   `no_price_dollars` / `yes_price_dollars`, `fee_cost` (dollars),
   `order_id` and `fill_id`; the legacy `count` / cents fields may be
   absent. `normalize_fills()` maps either shape to one, applied at
   ingestion. The test uses the current shape.
3. **Starting queue at placement.** Each accepted order's queue position is
   read immediately after the exchange accepts it (`queue_ahead_at_place`
   in the ledger); the 15-minute sweep remains for the path afterwards.
4. **Order-level profit.** Realised profit is now computed from the order's
   own buy fills and the market result (`(payout − price) × contracts −
   fee`), not from the account's per-ticker settlement, so entries and
   exits in the same market do not mix. `cents_per_settled_contract` is the
   number to set against the backtest's 2.9¢.

Also recorded per order: `accept_utc` (exchange acceptance time) against
the run's signal time, for the signal-to-acceptance delay. The 500-fill
scorecard: capture of qualifying volume, fill probability by starting
queue, cents per settled contract (game-clustered t), profit per eligible
order including unfilled, minutes to first fill.


## 2026-10-17: Forward-validation protocol frozen (measurement only)

At the start of the forward cohort, the trading/research baseline is commit
`1167400bc246ab324472eefc6a24bdb8e2cf7d52`. The experiment is
specified in `docs/FORWARD_VALIDATION.md`: 30 days from first exchange-
accepted real order AND 500 settled exchange buy fill events before a human
review. No automated rule or capital changes. Retain old qualifying-volume
observations beyond the API's three-day refetch horizon; distinguish partial
and complete observations; calculate *volume-weighted* capture (not the
simple average of per-order ratios). Exclude early-exit markets from the
buy-and-hold payout proxy pending reconciled realized P&L. Flag missing data
and game-level dependence explicitly.

## 2026-10-18: Polymarket, feasibility before any scan

Question: can the Kalshi research (resting "no" on player props) be repeated
on Polymarket? Checked before building anything (`research/polymarket/probe.py`,
run on Actions; `outputs/polymarket/probe.md`, `markets.csv.gz`).

**Access and fees.** Polymarket's CFTC-regulated US app is live in Texas as
of 2026-10-16 with NBA/NFL/NHL/soccer markets (CBS Sports, 2026-10-16).
Makers pay no fee and receive 10–25% of taker fees as rebates; takers pay
about 5% × p × (1 − p) on sports (≈1.75% at 50¢). Structurally better for a
maker than Kalshi's fee. Unknown: whether the US app shares an order book
with polymarket.com, whose public API carries the history.

**Data.** `data-api /trades` returns public prints with taker side, price,
size and time (the same input the Kalshi simulator uses);
`clob /prices-history` returns an hourly price series for open markets and
nothing for closed ones; `/book` gives the current book only. So a fill
simulation is possible, with the posting price inferred from the last
trade rather than a historical bid/ask (a known weakening).

**Inventory, the deciding fact.** 335,615 unique sports markets listed;
34,998 are per-game player props by question text, with **$9.7M total
volume and a median of $0**: most are empty listings. Closed props with at
least $1,000 of volume: **743** (NFL anytime touchdown 232, soccer
goals-threshold 191, NFL yards/receptions 177, NBA points 70, NFL 2+ TD
56). The 70 NBA points markets are all 2024-25 playoff one-offs ("NBA
Finals G1: Will SGA score 34+ points"); there is no regular-season NBA
prop history. For comparison the Kalshi NBA prop replay had 21,373 fills
in one season.

**Reading.** The market where the edge lives (regular-season NBA props
with a retail crowd) does not yet exist on Polymarket in testable size;
what can be scanned is NFL scorer props (flat on Kalshi) and soccer
goal-threshold markets (a game market). Polymarket US lists "Player Prop"
as a contract type, so volume may arrive this season. Decision pending:
either run the small scan on the 743 markets now, or snapshot the
inventory weekly and scan when NBA prop volume exists.

## 2026-10-21: Live rule changes since launch (operational record)

Not a test: this entry records the rule changes made for live trading so the
log stays complete. Each one is described in the linked documents, and none
of them is evidence of profit.

- **19–20 October:** the NFL and NBA bots were switched on together on one
  funded account ([DUAL_MARKET_PRODUCTION.md](deploy/DUAL_MARKET_PRODUCTION.md)).
- **20–21 October:** NBA rules v4 (`nba-no-v4-smaller-orders-edge3-baseline`).
  New orders start 2–6 hours before tip-off and rest until tip-off; the second
  cent of price improvement is off (it lost in the replay, see *What did not
  work* in the README); an order needs 3¢ of estimated edge after fees both to
  be placed and to stay.
- **21 October:** limits sized for the $250 account, account-wide loss stops
  (−$20 a day, −$60 total, NBA and NFL settled markets together) and a
  15-minute hold when inputs fail for connection reasons only. Current values:
  [PROD_NBA_AUTO.md](deploy/PROD_NBA_AUTO.md#execution-policy).
- Live results are judged only under the
  [forward-validation protocol](docs/FORWARD_VALIDATION.md), with each rule
  version counted as its own group.

## 2026-10-21: Fill and sizing replay (exploratory)

**Exploratory, in-sample.** No plan was written before these runs, and no live
rule was changed because of them. About 20 rule variants and two capacity
sweeps were tried; the rows below are the live rules, the two strongest
alternatives and the capacity sweep. Treat every comparison as unadjusted
for that search.

### Question
With a $250 account, which settings collect the most separate fills per
night, and how do profit and drawdown change as orders get bigger?

### Method
`python -m research.fill_sizing_replay` replays every 2025–26 NBA market's
hypothetical resting NO order against Kalshi's public trade prints. An order
fills up to the contracts that traded at or through its price before tip-off,
as if first in line; `flow_share` 0.25 gives each traded contract a one-in-four
chance of reaching us. Caps, including the lifetime allowance, are charged in
the live bot's order (day, tip time, best edge first); a night that loses the
daily stop blocks the next night. No maker fee is charged (NBA prop series
reported none in October 2026; earlier entries charged a quarter of the
taker fee). Statistics are game-clustered.

### Results (183 nights)

| Rules | Nights with orders | Filled orders a night | ¢ per contract | t | Season P&L | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|
| Live now: 2 contracts, 3¢ edge, 10/game, $75 a night, $1,000 lifetime | 37 | 13.2 | 0.81 | 0.3 | $8 | −$15 |
| Live now without the lifetime allowance | 183 | 25.7 | 3.97 | 4.6 | $368 | −$27 |
| 2 contracts, 0¢ edge, 25/game, $150 a night | 182 | 53.8 | 3.77 | 5.8 | $729 | −$56 |
| 1 contract, 0¢ edge, 5–95¢, 40/game, $150 a night | 183 | 79.1 | 3.32 | 6.1 | $481 | −$23 |

The $1,000 lifetime allowance counts every order placed, filled or not. At
the live rules the replay places about $43 of orders a night, so the
allowance runs out after 37 nights (about 480 filled orders); the bot then
stops placing new orders until the owner raises it. Those first 37 nights
happened to be weak (0.8¢ per contract). The other rows place $43–$95 a
night and would need a larger allowance.

Capacity, 25 orders a game and no cash limits, first in line vs a quarter
of the flow:

| Contracts per order | P&L, flow 1 | P&L, flow 0.25 | ¢ per contract (0.25) | Max drawdown (0.25) |
|---:|---:|---:|---:|---:|
| 1 | $416 | $385 | 3.61 | −$21 |
| 10 | $3,906 | $3,301 | 3.64 | −$225 |
| 100 | $28,235 | $17,460 | 3.32 | −$1,847 |
| 1,000 | $113,930 | $42,679 | 2.76 | −$18,955 |

### Findings
- One contract per order and looser per-game limits roughly triple the
  number of separate fills compared with the live rules, at lower profit per
  contract. Separate fills are what the live evaluation needs.
- Profit grows much more slowly than order size: big orders fill only
  partly, and the props that fill them trade on more informed flow.
  Drawdown grows about $20 per contract of order size.
- Ad hoc check on the same data: orders with 15–25¢ of model edge lost
  0.3¢ per contract in the regular season (932 filled orders), so the 15¢
  edge cap stays. A second cent of price improvement added about two fills a
  night but cut profit per contract by about 0.5¢.
- All of this is in-sample with optimistic fills; live results will be lower.

## 2026-10-21: Do star players' props deserve bigger orders? (plan)

*Written before running anything. Results are appended below the plan.*

### Question
A scenario table circulated today assumed star players' props earn either
more (4.5¢ vs 3.2¢) or less (2.5¢ vs 4.0¢) per contract than other players'
props, and that extra contracts on stars fill at the same rate. Measure
instead: do resting NO orders on stars earn a different amount per contract,
and does giving star props more contracts per order raise profit relative to
drawdown?

### Method (fixed in advance)
- **Base replay:** `research.fill_sizing_replay` rules with 1 contract per
  order, 0¢ minimum edge, 15¢ edge cap, 10–90¢ prices, 25 orders a game, no
  cash limits; flow share 1 and 0.25. 2025–26 season, in-sample.
- **Star, definition S1 (primary):** the player's projected points for that
  game (`model_mean` on his points markets) is 20 or more. Known before the
  game. A player with no points market that game is not a star.
- **Star, definition S2 (secondary, popularity):** the player's average
  traded contracts per market over his earlier games (strictly before that
  day, at least 3 games) is in the top 30% of all player-games. The 30%
  cut-off is taken over the whole season (a mild look-ahead, noted).
- **Comparison:** ¢ per filled contract for stars and for everyone else, and
  the star-minus-other difference with game-clustered t; fill rate and
  traded-through volume by group.
- **Weighting:** stars get 2, 3 or 5 contracts per order, everyone else 1;
  fills are capped by the contracts that actually traded through the price
  (times the flow share). Report P&L, ¢ per contract, max drawdown and P&L
  per dollar of drawdown.
- **Robustness:** regular season only; first and second half of the season
  (split at the median date).
- **Variants:** 2 definitions × 4 weightings × 2 flow shares = 16 replays,
  plus the group comparisons in 3 samples. All are reported.

### Pass/fail bar
- **Weight stars up** only if, under S1, stars beat everyone else by at
  least 1¢ per contract with t ≥ 2 on the full season, the sign holds in both
  halves and in the regular season, and 2× weighting improves P&L per dollar
  of drawdown at flow share 0.25.
- **Look at weighting stars down** (a separate future test) if stars trail
  by at least 1¢ with t ≤ −2 under the same conditions.
- Otherwise: keep equal weighting. No live rule changes either way without
  the owner's approval.

### Results (run after the plan above was committed)

`python -m research.star_weighting`; numbers also in
`outputs/research/star_weighting.json`. 2025–26, in-sample, simulated fills.

**Stars versus everyone else, 1 contract per order, flow share 1:**

| Definition | Sample | Star ¢/contract | Other ¢/contract | Difference | t |
|---|---|---:|---:|---:|---:|
| S1 projected points ≥ 20 | Full season | 4.58 | 3.18 | +1.41 | 1.08 |
| | Regular season | 3.86 | 3.31 | +0.55 | 0.39 |
| | First half | 4.58 | 2.99 | +1.59 | 0.85 |
| | Second half | 4.59 | 3.29 | +1.30 | 0.71 |
| S2 most-traded players | Full season | 2.96 | 4.05 | −1.09 | −0.81 |
| | Regular season | 1.82 | 4.09 | −2.27 | −1.42 |
| | First half | 3.02 | 3.85 | −0.84 | −0.25 |
| | Second half | 2.95 | 4.31 | −1.37 | −0.86 |

S1 stars were 35% of orders and filled more often (66% against 59%), with
far more trading at our price (median 36 contracts against 11).

**Weighting stars, flow share 0.25 (average of 5 draws):**

| Star contracts per order | S1 P&L | S1 max drawdown | S1 P&L per $ of drawdown | S2 P&L per $ of drawdown |
|---:|---:|---:|---:|---:|
| 1 (equal weighting) | $398 | −$20 | 19.6 | 19.6 |
| 2 | $566 | −$30 | 19.0 | 18.3 |
| 3 | $727 | −$47 | 15.4 | 15.1 |
| 5 | $1,035 | −$81 | 12.8 | 10.4 |

### Verdict: fail; keep equal weighting
- S1 stars earned about 1.4¢ more per contract, but t = 1.1 (below 2), and
  only 0.55¢ more in the regular season. The gap is within noise.
- The most-traded players (S2) earned *less* in every sample, though not
  significantly. Popular players' props seem to draw sharper traders, not
  just fans.
- Doubling star orders adds profit roughly in line with the extra drawdown,
  so profit per dollar of drawdown does not improve (19.0 against 19.6 at
  flow share 0.25). Bigger multiples make it worse.
- The scenario table's assumption that extra star contracts fill as easily
  roughly held: star props have much more trading at our price, so they can
  absorb more size. That matters for scaling up later, not for edge.
- 16 replays and 8 group comparisons were run, all reported above.
- Not tested, for a future pre-registered test on 2026–27 data: high-scoring
  players who are *not* among the most traded (S1 and not S2).

## 2026-10-21: NBA rules v5, more orders for faster evidence (plan)

*Written before the v5 code change. Approved by the owner on 21 October
2026. Results will be appended below, without editing this plan.*

### Why
At the v4 rules the replay reaches about 480 filled orders before the $1,000
lifetime allowance runs out, too few to tell a 3¢ edge from luck (about
1,900 are needed once same-game correlation is counted). v5 places more,
smaller orders so that question can be answered sooner. Pricing does not
change: one cent better than the best NO bid, post-only, resting until
tip-off.

### What changes (`nba-no-v5-one-contract-breadth`)
| Setting | v4 | v5 |
|---|---|---|
| Contracts per order | 2 | 1 |
| Minimum edge to place and to keep | 3¢ | 0¢ (15¢ cap unchanged) |
| Price range | 10–90¢ | 5–95¢ |
| Orders per game | 10 | 40 |
| Cost per game / per team per day | $15 / $10 | $25 / $25 |
| New orders per day; open at once | $75; $75 | $150; $150 |
| New orders per scan | 1 | up to 3 |
| Lifetime allowance | $1,000 | $2,000 |
| Account-wide daily / open / lifetime | $105 / $90 / $1,050 | $180 / $165 / $2,050 |
| Loss stops | −$20 a day, −$60 total | unchanged |

Replay expectation (2025–26, in-sample, first in line): about 1,900 filled
orders over about 51 game nights before the $2,000 allowance runs out; live
fills may be half that rate.

### How v5 will be judged
- **Group:** every order whose journal intent says
  `nba-no-v5-one-contract-breadth`, counted from its first accepted order.
  v4 orders stay a separate group.
- **Primary measure:** settled profit per filled contract, after actual
  fees, with game-clustered t.
- **Checkpoint:** when the $2,000 allowance runs out or 1,900 settled fills,
  whichever comes first, and in any case at 30 days.
- **Reading the result:** t ≥ 2 and positive means the edge is real at these
  settings; positive but t < 2 means keep collecting; t ≤ −1 at the
  checkpoint means stop and review.
- **Reported separately, decided in advance:** orders with at least 3¢ of
  edge at entry against those under 3¢; sportsbook-priced against
  model-priced; orders where the model's view and the books' differ by 5
  points or more against the rest; live fill rate against the replay's.
- **Stops:** the existing loss stops (−$20 a day, −$60 total, account-wide)
  apply throughout; no limit is raised during the evaluation.

### Addendum to the v5 plan (21 October, before any v5 order)
Added after the independent code review, before v5 was deployed or placed
any order:
- **Also reported separately:** orders priced 5–9¢ or 91–95¢, which v4's
  10–90¢ range never traded live.
- **Effective entry floor:** the candidate stage subtracts an estimated maker
  fee (about 0.4¢ near 50¢) even when the live fee is zero, so new orders
  need slightly more than 0¢; resting orders are kept down to exactly 0¢.
- **Operational changes that do not affect selection:** no new order after
  150 seconds of a scan's runtime, fee metadata fetched once per series and
  game per scan, and queue position observed at most every 10 minutes per
  order.

## 2026-10-21: Official NBA injury report as a second news source (operational)
Not a test; recorded because it changes which v5 orders are placed and kept.
- **What:** from its deploy, the NBA worker also reads the league's official
  injury report (published every 15 minutes) each scan and adds vetoes on top
  of ESPN's, per game date: Out/Doubtful players, Questionable players
  (teammates then need two fresh books), teams whose high-risk listings
  changed since the projections, teams not yet submitted. It never removes a
  veto and fails open (ESPN only) when the report is unreadable. Rules in
  `deploy/PROD_NBA_AUTO.md`. An independent review before deploy found that
  the first draft keyed vetoes by team only (tomorrow's back-to-back listing
  would have vetoed tonight) and had an "ahead of ESPN" rule that could flip
  many model-priced rows on a name mismatch; both were fixed (the second
  rule was dropped) before any live use.
- **Effect on the v5 evaluation:** the strategy version is unchanged, so
  orders before and after the deploy are both v5. They are reported as two
  sub-groups split at the deploy time, in addition to the groups already
  listed. Cancels now record their veto, so official-report cancels can be
  counted.
- **Exploratory question for later:** do markets cancelled for official
  report news move against the order before tip-off more often than other
  resting markets (the "picked off" risk this is meant to avoid)? No pass/fail
  bar; it needs a pre-registered plan before any confirmatory claim.

## 2026-10-21: Adverse selection on live v5 fills (plan)

*Written before any live outcome was looked at, and revised once before
merging (still before any outcome was seen) after a simulation showed the
first checkpoint was too small; see "Power". Running numbers shown in the
owner's private nightly report before the checkpoint are monitoring only;
nothing is decided from them.*

### Question
Do the orders that get filled lose more often than the sportsbooks' price
said, compared with orders that rested at the same kind of price but did
not fill? In other words, is P(NO | filled) below P(NO) at entry? If
informed traders are the ones filling us, the edge we estimate at entry
(`Edge(NO) = P(NO) − price − fees`) overstates the edge we actually earn.

### Method
- **Orders:** live NBA orders with strategy version
  `nba-no-v5-one-contract-breadth`, accepted by the exchange and priced by
  the sportsbooks (two or more books).
- **Outcome:** each market's result from Kalshi's public results
  (`data/kalshi/2027/results/`), so unfilled orders are scored too.
- **Per order:** surprise = (1 if NO won, else 0) − fair NO at entry, where
  fair NO = 1 − the sportsbooks' de-vigged probability at entry.
- **Comparison:** mean surprise of filled orders against orders that never
  filled, from a regression of surprise on a filled indicator with
  standard errors clustered by game. Orders cancelled before tip-off are
  reported separately (they were cancelled for a reason, such as injury
  news or a lost edge), and the main comparison uses orders that rested
  until tip-off.
- **When:** once, at the v5 checkpoint (1,900 settled fills, the $2,000
  allowance or 30 days, whichever comes first). No earlier look counts.

### Pass/fail bar (one test, one variant)
Adverse selection is **found** if filled orders' surprise is below the
unfilled orders' by at least 1¢ with t ≤ −2. Then a new plan, written
first, tests raising the minimum edge by the measured gap. Otherwise
nothing changes.

### Power
One contract's result has a standard deviation of about 50¢. With about
1,900 filled and a similar number of rested, unfilled orders, the standard
error of the difference is about 1.5–2¢ before clustering, so only a gap of
roughly 3–4¢ or more can pass t ≤ −2. A simulation with a true 3¢ gap and
2,000 orders gave t ≈ −0.9. A result that does not pass therefore means
"no large adverse selection", not "none"; a 1¢ gap would need tens of
thousands of orders.

### Caveats
Unfilled orders were further back in the queue, so the two groups are not
randomly assigned; a difference could also come from where in the queue
an order sat. Queue position at posting is reported alongside.

## 2026-10-21: Market-making models applied to the NO seller (plan)

*Written before any of these tests was run. Exploratory and in-sample: the
v5 rules were chosen on 2025-26, the only season with Kalshi player props.
A pass here only qualifies an idea for a written-down forward pilot; it is
not evidence that it works.*

Prompted by an outside article on optimal quoting (Avellaneda-Stoikov,
Glosten-Milgrom). Five ideas, translated to one-sided resting NO orders held
to settlement. `research/article_tests.py`.

### Common setup
- **Orders:** the 2025-26 replay orders (`outputs/decompose/orders_no.csv.gz`,
  one per market, mostly posted 5 hours before tip), fair value = the frozen
  stat model's probability, priced one cent better than the best NO bid when
  the spread allows (else joining it), no maker fee (NBA props have none).
- **Fills:** contracts a YES taker bought through our price before tip-off
  (at our price only when we improved the market), as if first in line.
  Every comparison is run at `flow_share` 1.0 and 0.25 (each contract that
  traded reaches us with that chance; 0.25 averaged over 10 random draws).
- **Rules (v5-like):** 1 contract, 0-15¢ edge, 5-95¢, 40 orders and $25 per
  game, $25 per team and $150 a night, the −$20 nightly stop. The lifetime
  allowance and cumulative stop are off, so every variant sees the whole
  season.
- **Statistics:** game-clustered t; "both halves" = the season split at its
  median game date.

### Tests, variants and pass bars (14 variants in all)
1. **Profit decomposition** (descriptive, no variant). Profit per filled
   contract = entry edge + surprise (outcome − fair value). Adverse
   selection = surprise of filled orders − surprise of unfilled orders
   (clustered t). Inventory: the within-game correlation of filled
   contracts' results and the variance it adds per night.
2. **Minimum edge (Glosten-Milgrom).** Minimum edge 1, 2, 3 and 4¢ against
   0¢ (4 variants). Pass: season P&L at least 10% above 0¢ at both flow
   shares and in both halves, with cents per contract t ≥ 2.
3. **Time to tip-off (Avellaneda-Stoikov's horizon term).** Orders rebuilt
   from hourly quotes posted 2, 4 or 6 hours before tip, each with a minimum
   edge of 0 or 0.5¢ per hour before tip beyond 2 (6 variants), against
   orders posted 5 hours before with 0¢ (control, rebuilt the same way).
   Pass: season P&L at least 10% above control at both flow shares and in
   both halves. Caveat written now: the replay puts every improving order
   first in line whenever it was posted, so it cannot show the queue
   advantage of posting earlier, only the price and selection effects.
4. **Same-game inventory penalty (Avellaneda-Stoikov's inventory term).**
   The k-th order in a game needs an extra (k − 1) × c of edge, for c = 0.1,
   0.25 and 0.5¢ (3 variants). Pass: Sharpe ratio of nightly P&L at least
   10% above control at both flow shares and in both halves, with season
   P&L no more than 10% below control.
5. **Fill-probability quote choice (order arrival intensity).** For each
   order, choose join, improve 1¢ or improve 2¢ (when the spread allows) to
   maximise P(fill) × edge, P(fill) from a logistic model fitted on the
   first half using only what is known when posting (spread, price, option,
   hours before tip, open interest at posting). 1 variant, against always
   improving 1¢, scored on the second half: profit per 100 eligible orders
   (one contract each, unfilled count zero). Pass: at least 10% above the
   control with the paired difference's game-clustered t ≥ 2 at flow share
   1.0, and above control at 0.25.

**Related earlier tests on the same season** (added before running, so the
multiplicity is visible): a 2¢ minimum edge (`edge2` in the placement study
and the `no_seller_veto2` paper ledger, both fewer orders and less profit
per 100 eligible orders); a second cent of price improvement
(`quote_placement.py`, less profit); posting 2 hours instead of 5 before tip
(+4.5¢ against +1.4¢ per fill in the decomposition, the `no_seller_late`
ledger); and cancelling unfilled orders after 30-180 minutes (less profit).
Tests 2, 3 and 5 overlap with these, so their bars are read as confirmation
of earlier exploratory results, not as new discoveries. Counting those four,
this season has now been used for at least 18 variants of these ideas.

Two details settled before running: in test 3, at 2 hours the 0 and 0.5¢
per hour rules are the same rule, so 5 of the 6 variants are distinct; and
the trade prints on file start 6 hours before tip, so an order posted 6 or
more hours before can only fill from then on.

Results will be appended below this plan without editing it.

## 2026-10-21: Market-making models applied to the NO seller (results)

*Simulated and in-sample (2025-26, the season the v5 rules were chosen on).
Run once as planned above, `python -m research.article_tests`; tables in
`outputs/research/article_tests.md`. 14 variants as registered (13
distinct); with the four earlier related tests, at least 18 on this season.
None passed its bar, so nothing changes in the rules.*

Checks before reading the results: the season loop reproduces
`fill_sizing_replay.simulate` exactly ($481.04 under the v5-like rules), and
orders rebuilt from hourly candles at 5 hours reproduce all 48,868 original
5-hour orders (price, posting time and traded-through volume). An
independent recomputation (written without this module) matched the season
P&L, the decomposition and test 5's control exactly. Its review led to three
small fixes before this entry, none of which moved a pass/fail result: open
interest missing at posting is now filled from the first half only (test 5,
no number changed), and the nightly variance ratio below is now measured
around the average result rather than the model's edge (2.3 became 1.7).

**A caveat that matters for every test.** Among filled replay orders, the
median volume traded through our price was 164 contracts, so giving each
contract a 25% chance of reaching us (flow share 0.25) rarely changes
whether a one-contract order fills (fills fall only 5%). The 0.25 runs are
therefore not a real stress test for one-contract orders. The real unknown
is queue position, which the replay does not model. In public Kalshi
snapshots from 20-21 October 2026 (2-6 hours before tip), 61% of the rungs
with a two-book sportsbook line, the only ones v5 trades, had a 1¢ spread,
where an order can only join the queue.

1. **Where the profit per filled contract comes from** (v5-like caps, flow
   share 1.0; 0.25 in brackets). 14,478 filled contracts made +3.32¢ each
   (t 6.10) [13,726, +3.31¢]. That splits exactly into:
   - entry edge, the model's fair value minus our price: +6.40¢ [+6.42¢];
   - model error, measured on the orders that did not fill: −5.10¢
     [−4.90¢]. Picking orders where the model disagrees with the market
     picks the model's own mistakes, so about 5¢ of the stated edge is not
     real;
   - selection by the fill, filled minus unfilled outcomes: **+2.02¢,
     t 2.96** [+1.79¢, t 2.66]. Fills were *favourable*, not adverse: the
     orders YES buyers took did better than the ones they left. Across all
     53,549 orders with no caps: +2.35¢ (t 4.87).
   - By placement, the favourable selection belongs to the orders one cent
     inside the spread: +2.62¢ (t 3.56) among v5-like placed orders, +2.85¢
     (t 5.46) across all orders. Orders that joined the NO bid got none:
     −1.54¢ (t −1.01) placed, +0.27¢ (t 0.26) across all orders. A joined
     order fills only when YES trades *through* its price, which tends to
     follow news against NO (the textbook adverse selection), so it loses
     the benefit of being filled by fans at the ask. Joined orders also earned less
     per filled contract (+2.81¢, t 2.19, 1,473 fills) than improving ones
     (+3.38¢, t 6.02, 13,005 fills). They were 13% of the replay's
     orders; this season most rungs v5 can trade have a 1¢ spread (above),
     so joining is far more common live.
   - Inventory (holding to settlement has no expected cost, only risk):
     results of filled contracts in the same game correlate at 0.06; with
     about 21 fills per game that makes the variance 2.2 times what
     independent contracts would give (design effect 2.18), and nightly P&L
     varies 1.7 times as much as independent contracts would. This is the
     900 → 1,900 fills arithmetic in `CLAUDE.md`.
   - The fill rate did not depend on the edge: 61% for 0-3¢ and for 3-15¢.

2. **Minimum edge: fails at every level.** Cents per contract rise with the
   minimum (+3.32¢ at 0¢ to +3.69¢ at 4¢), but the orders lost cost more:
   season P&L $481 (0¢), $472 (1¢), $445 (2¢), $413 (3¢), $375 (4¢) at flow
   share 1.0, the same order at 0.25 and in both halves. Agrees with the
   earlier `edge2` and `no_seller_veto2` results.

3. **Posting time: fails.** On the same markets, rebuilt 2, 4, 5 and 6
   hours before tip (control 5 hours, $431 at 1.0, $412 at 0.25): 2 hours
   $431 / $408; 4 hours $463 / $433 (+7% and +5%, short of the 10% bar, and
   below control in the first half); 6 hours $295 / $286 (2.3¢ per
   contract against 3.2¢). Asking for 0.5¢ more edge per hour made 4 and 6
   hours worse. The earlier "2 hours before tip made +4.5¢ against +1.4¢ at
   5 hours" does **not** hold on the same markets (+3.27¢ against +3.15¢
   here): it compared different markets, those first priced 2 hours before
   tip having opened late. Caveat from the plan: the replay puts every order
   first in line whenever it was posted, so posting earlier gets no queue
   credit here.

4. **Same-game inventory penalty: fails.** Nightly Sharpe ratio 0.48 with no
   penalty; 0.48, 0.44 and 0.37 at 0.1, 0.25 and 0.5¢ per order already in
   the game, with season P&L $458, $355 and $250 against $481 (flow share
   1.0; 0.25 the same). With a correlation of 0.06, the extra orders in a
   game add more expected profit than risk.

5. **Choosing join / improve 1¢ / improve 2¢ by P(fill) × edge: fails, and
   loses.** Second half, 22,135 eligible orders: −11.8¢ per 100 orders
   against always improving 1¢ (t −2.68) at flow share 1.0; −14.6¢
   (t −3.39) at 0.25. The fill model was well calibrated (join predicted 35%,
   actual 34%; improve 1¢ 64% vs 67%), so the loss is what the score leaves
   out: it treats the edge at entry as the profit if filled, and joined
   fills are the adversely selected ones (point 1). It chose to join on 29%
   of orders.

**What carries forward.** The rules stay as they are (0¢ minimum, one cent
inside when the spread allows, no same-game penalty, 2-6 hours). The useful
lesson is Glosten-Milgrom's: profit is the edge at entry plus what being
filled says about the outcome. In the replay that second part was about
+2.6¢ to +2.9¢ for improving orders and about zero (−1.5¢ to +0.3¢) for
joined ones, and this season most rungs v5 trades allow only joining. The
pre-registered live adverse-selection check (this log,
2026-10-21) should therefore also be read separately for joined and
improving orders at the v5 checkpoint, as a description, not a new test.

## 2026-10-22: Where is the NO edge thicker? (exploratory plan)

*Exploratory and in-sample (2025-26), written before running. Nothing here
changes the live rules. Anything promising becomes its own written plan,
tested forward on 2026-27 beside the unchanged v5 rules.*

Live v5 orders carry about 1-1.5¢ of estimated edge against the sportsbooks
(21 October). Four places the edge could be thicker:

**Common setup** (A and B, `research/explore_edge.py`): the replay orders
under the v5 filter (one contract, 0-15¢ of model edge, NO 5-95¢), no caps
(so caps do not distort the slices), fills as if first in line (flow share
1.0) and at 0.25 (expected value over the thinning), game-clustered t,
halves split at 2026-02-09. A slice counts as **promising** only if its
cents per filled contract beat the rest of the season with a clustered t of
at least 2 for the difference, the difference is positive in both halves,
and it has at least 1,000 fills.

- **A. Who is on the other side:** NO price (6 bands); line minus the
  model's mean (5 quintiles); the market's trading volume before posting (5
  quintiles); the whole game's prop volume before posting, a stand-in for
  national TV and star power (5 quintiles); tip-off time (3); weekend or
  weekday (2); regular season, play-in or playoffs (3); stat (4).
- **B. Being first in line:** spread at posting (1, 2, 3-4, 5¢+: 4 bins);
  market age at posting (under 24, 24-48, over 48 hours: 3 bins); and,
  descriptively, the share of markets with a spread of 2¢ or more at 2-6
  hours before tip.
- **C. Ladder prices from the sportsbooks** (`research/explore_ladder.py`):
  a count distribution fitted to every sportsbook line for the player, stat
  and game (negative binomial and normal: 2 variants), pricing every Kalshi
  rung. Judged on calibration against outcomes (log loss) beside the stat
  model and Kalshi's mid, and on replay profit for rungs that lack a
  two-book exact line, in the 151 games with sportsbook history.
- **D. Other markets** (`research/explore_markets.py`): the 2025-26 combo
  markets (double-double and triple-double) re-scored with game-clustered t
  and halves; and the cross-market scan re-scored with a time holdout (rank
  series on the earlier half of their markets, test the top 10 on the later
  half).

Variant count: 40 slice bins (A, B), 2 (C), 12 (D): 54 in all. At t ≥ 2,
about 1 of the 40 slice bins would look promising by chance alone.

Results will be appended below this plan without editing it.

## 2026-10-22: Where is the NO edge thicker? (results)

*Exploratory, simulated and in-sample (2025-26 and the scan's samples),
run once as planned above. Tables: `outputs/research/explore_edge.md`,
`explore_ladder.md`, `explore_markets.md`. 54 planned variants plus 12
extra in D (ranking by t instead of cents, and four combo variants): 66.
Nothing here changes the live rules.*

**A and B, slices of the NBA replay** (v5 filter, no caps, first in line;
flow share 0.25 changes nothing material). Of 40 bins, 1 met the bar
(the second quintile of line minus the model's mean: +4.47¢ per contract,
+1.62¢ above the rest, t 2.06), about what chance alone gives (0.9); its
neighbours are not in order (fourth quintile −1.61¢, t −2.35), so it reads
as noise. Two weak spots were consistent in both halves, though still
profitable: **rebounds** (+1.15¢, 2.65¢ below the rest, t −2.59; known
since 2026-10-15) and **the busiest markets**, the top fifth by trading
before posting (+1.66¢, 2.02¢ below, t −2.54). Busy markets look more
efficient, not more fan-heavy. Spread at posting points the same way as
the 21 October tests (1¢: +2.23¢ with 46% filled; 5¢ or more: +3.62¢ with
57% filled), not significantly.

**Room to go first in line.** In 2025-26, 81-85% of prop markets had a
spread of 2¢ or more 2-6 hours before tip. In public snapshots of 20-21
October 2026, 39% of the rungs with a two-book sportsbook line had one,
against 80% of the rungs without. v5 trades only the former, so this
season it mostly joins queues on the tightest rungs.

**C, ladder prices from the sportsbooks** (150 games with book history,
7,218 rungs). The fitted ladders reproduce the books' own lines (median
error 0.4 points for the negative binomial). On the 4,678 rungs without a
two-book line, they predicted outcomes better than the stat model (log loss
0.4684 against 0.4814, t −3.34) and better than Kalshi's price at posting
(0.4798, t −3.18). In the replay on those rungs the negative-binomial
ladder made fewer but better orders: 1,183 fills at +4.59¢ (t 3.13)
against the current rule's 1,568 at +2.26¢ (t 1.70). The ladder's stated
edge (1.9¢) undershot what it made, while the stat model's (5.3¢)
overshot by 3¢. The total gain per rung over the current rule was +$0.40
per 100 rungs (t 1.29) for the negative binomial and +$0.51 (t 1.78) for
the normal, positive in both halves but mostly in the first. On rungs
with a two-book line the ladder is worse than the book line itself, as
expected. **The one candidate from this exploration:** price rungs without
a two-book line from the fitted ladder. That is where the wide spreads are.

**D, other markets.** The scan's best series mostly do not survive a time
holdout: the top 10 on the earlier half of their samples averaged +19.2¢
there and +3.1¢ on the later half (pooled +1.2¢, t 0.44). Only college
basketball first-half spreads (`KXNCAAMB1HSPREAD`) passed every check
(+14.8¢, t 2.84, on the later half; survives a 10% false-discovery-rate
correction); it is already on the paper ledger from November. Club soccer
both-teams-to-score and NCAA mention markets are a weaker second tier
(short samples), also already on paper. NBA double-doubles fail (+2.7¢,
t 1.02); triple-doubles are thin and longshot-heavy (+4.5¢, t 2.25, 37% of
fills at NO 96¢ or more). Scans of hundreds of series produce false
winners: 45 series had t ≥ 2 against about 16 expected, but 20 had t ≤ −2.

**What carries forward.** One written forward plan is worth drafting:
ladder pricing for rungs without a two-book line, run as a separate paper
ledger beside the unchanged v5 rules, judged on 2026-27 outcomes.
Rebounds and the busiest markets stay in v5 (still profitable); NCAA
first-half spreads proceed on paper in November as already planned.

## 2026-10-22: Two proposed NBA strategies, ladder maker and totals maker (research plan)

*Written before running. Exploratory; nothing here changes the live rules.*

The owner proposed two paper strategies beside v5: (1) an **NBA sportsbook
ladder maker**, which prices every player-prop rung from a distribution
fitted to all sportsbook lines (exploration C above), and (2) an **NBA
totals maker**, which posts NO on Kalshi game-total contracts
(`KXNBATOTAL`, YES when the final total is above the strike) priced from
sportsbook over/under lines. The proposal quotes +4.59¢ per simulated
filled contract for (1) and +3.45¢ for (2) "across the archived sample,
simple NO strategy, 1¢ fee".

**Ladder maker** (`research/two_strategies.py ladder`), descriptive only:
- the NB ladder's replay on rungs without a two-book line (exploration C),
  split by stat (4), number of book lines for the player and stat (1, 2,
  3+), spread at posting (1¢, 2¢+) and distance from the nearest book line
  (0, 1-3, more than 3): 12 bins, reported without pass bars;
- this season's feed: alternate-line coverage in `outputs/books`, and the
  share of Kalshi rungs (public snapshots) that get a ladder price but lack
  a two-book line, with their spreads;
- a pipeline check on this season's nights with logged results, too small
  to be evidence.

**Totals maker** (`research/two_strategies.py totals`):
- trace the +3.45¢ figure and re-score the archived scan rows
  (`outputs/scan/orders_KXNBATOTAL.csv.gz`) with game-clustered t, both
  fee assumptions (0 and 1¢ per contract) and both halves;
- fair value P(final > strike) from ESPN's game total (`data/games.parquet`)
  and the distribution of (final − ESPN total) fitted on 2020-21 to
  2024-25 only: normal and empirical (2 variants). Judged against the
  outcome (log loss) beside Kalshi's mid at the order's quote time, and in a
  replay of the scan's hourly NO quotes (1-4.5 hours before tip, each
  resting one hour): an order when the edge is 0-15¢ and NO is 5-95¢, at
  most one filled contract per market, flow share 1.0 and 0.25;
- **lookahead caveat, written now:** ESPN stores one total per game,
  probably near the close, while the orders were quoted 1-4.5 hours before
  tip. Any edge here is an upper bound. Decision rule: if even this upper
  bound shows no edge (cents per filled contract at or below zero, or
  t < 1 with no fee), drop totals; if it shows one, the honest test needs
  time-stamped sportsbook totals at posting time before any paper ledger;
- correlation between the game total and the player-prop NO results in the
  same game, since both strategies would hold the same games.

Variant count: 2 (totals), plus 12 descriptive bins (ladder).

## 2026-10-22: Two proposed NBA strategies, ladder maker and totals maker (results)

*Exploratory and simulated, run once as planned above
(`python -m research.two_strategies totals` and `... ladder PUBLIC`;
tables in `outputs/research/two_strategies_{totals,ladder}.md`). Nothing
here is live P&L or a forecast, and nothing changes the live rules.*

### Totals maker

- **The +3.45¢ figure could not be reproduced** from this repository's
  data; the only +3.45¢ in the scan's results is NFL passing yards, YES
  side (t 0.90). The archived
  NBA totals scan, NO side, every hourly quote as an order: 1,671 fills in
  620 games, +0.74¢ per contract with no fee (t 0.36) and −0.26¢ with a 1¢
  fee (t −0.12). One contract per market: +0.15¢ and −0.85¢. A simple NO
  strategy on NBA totals has no edge: unlike player props, the people
  buying totals are not mostly fans backing a player.
- **Priced from the sportsbook total** (ESPN's line; residuals fitted on
  6,442 games from 2020-21 to 2024-25, sd 17.9 points), as an upper bound:
  391 fills, +3.25¢ per contract (t 1.25) with no fee, +2.25¢ (t 0.86) with
  a 1¢ fee (normal); the empirical version +3.62¢ (t 1.36) and +2.62¢
  (t 0.99). Positive in both halves, never significant. The model's log
  loss beat Kalshi's mid by only 0.0034 (t −1.64).
- **Why it is an upper bound.** ESPN's line and Kalshi's price at quote time
  differ by about 1.5 points (sd), and every point of difference moved the
  final total by 1.74 points (correlation 0.14). That is what a line
  recorded later than our quote, near the close, would do. It cannot be
  told apart from a genuine Kalshi mispricing without sportsbook totals
  time-stamped at posting time.
- **Decision rule (plan above):** the upper bound has t ≥ 1 with no fee,
  so totals are not dropped. They cannot go to a paper ledger until
  time-stamped sportsbook totals exist: either logged from now on with the
  odds feed, or backfilled for 2025-26 from the odds provider's history.
- **Overlap with props:** every 10 points the game total beats the line
  raises the over rate of the same game's points props by 3.3 points
  (17,268 props, 1,030 games; correlation 0.14). A NO on the total and NOs
  on points overs in the same game lose together, so the two strategies
  would share game-level risk under the account caps.

### Ladder maker

- **The +4.59¢ figure is right as quoted** (exploration C, rungs without a
  two-book line, no maker fee on NBA props), with its caveats: 150 games,
  in-sample, first in line; the total gain over the current rule on the
  same rungs was not significant (t 1.3-1.8) and mostly first-half.
- **Splits** (2025-26, descriptive): the ladder beat the current rule in all
  four stats, both spread groups and all three distance groups. Strongest:
  rungs 1-3 points from the nearest book line, +6.78¢ (t 4.00) against
  +2.98¢; rungs with a spread of 2¢ or more, +4.61¢ (t 2.95) against
  +2.25¢. Weakest: ladders built from exactly two book lines, +1.23¢
  (t 0.30). Ladders from a single line made +13.9¢ (t 4.1, 127 fills),
  too good to take at face value.
- **This season's feed already has the alternate lines**: a median of 2
  and mean of 3.5 sportsbook lines per player and stat per snapshot, 44%
  with 3 or more, at no extra cost. Of 1,113 Kalshi rungs 2-6 hours before
  tip on 20-21 October (7 games; public snapshot times cover only some tip
  times), 177 (16%) have a two-book line, v5's whole universe, and 884
  (79%) would get a ladder price. 76% of those have a spread of 2¢ or more,
  against 34% of the two-book rungs.
- **Pipeline check on this season** (865 ladder-only rungs, 7 games, two
  nights: a check that the code runs on the live data formats, not
  evidence): log loss ladder 0.4296, stat model 0.4720, Kalshi mid 0.4264.
  Paper fills: ladder 229 orders, 101 fills, +$2.41; stat model 470 orders,
  256 fills, +$8.86.

**What carries forward.** The ladder maker is ready for a written paper
plan: it needs no new data and no server change, since a nightly research
job can score it from public files (projection ladders, sportsbook
snapshots, Kalshi snapshots, trade prints and results). The totals maker
needs time-stamped sportsbook totals first; that is an odds-feed change and
an owner decision.

## 2026-10-22: A different strategy across all scanned Kalshi markets (exploratory plan)

*Written before running. Exploratory; nothing here changes the live rules.*

The owner asked for a strategy separate from the resting-NO seller that
works across Kalshi's markets. Data: the cross-market scan's hourly quotes
(`outputs/scan/orders_*.csv.gz`; about 1,760 series in every category,
quotes 7 to 4 hours before each market's expected expiration, with the
result). One row per market at its first and last quote in that window.
Only the result and the quotes are used, no model.
`research/explore_strategies.py`.

**Strategies (taker: buy at the ask, held to settlement):**
- **S1, favourite-longshot.** Prediction markets are often said to overprice
  long shots. At the first quote, buy whichever side's ask is at least X,
  for X = 80¢, 90¢ and 95¢ (3 variants).
- **S2, momentum or reversal.** Where the mid moved at least 5¢ between the
  first and last quote (about 3 hours), buy the side it moved toward
  (momentum), or the other side (reversal), at the last quote's ask (2
  variants).
- **Calibration** (descriptive, no variant): realised YES rate minus the
  mid, by price band and by category, which says where any of this could
  come from.

**Costs:** Kalshi's taker fee, 0.07 × P × (1 − P) per contract, unrounded
(a large order); and rounded up to the cent on a one-contract order. One
contract per market, at the quoted ask (depth unknown).

**Statistics and bar:** event-clustered t; halves split at the median
market date of the whole scan. A rule is **promising** if, after the
unrounded fee, it makes money in both halves with t ≥ 2 on the later half,
at least 1,000 trades, and no single series supplies more than a quarter of
its profit. Categories (by series name: sports, mentions, weather,
economics, crypto, politics, entertainment, other) are ranked on the earlier
half only and the best is reported on the later half. Variant count: 5
rules, and 8 categories per rule reported descriptively.

## 2026-10-22: A different strategy across all scanned Kalshi markets (results)

*Exploratory and simulated; `python -m research.explore_strategies`, tables
in `outputs/research/explore_strategies.md`. 202,805 markets, 1,763 series,
99,555 events; halves split at 2026-05-10. Nothing here changes the live
rules.*

**The planned rules failed, and the plan had a flaw.** S1 as written ("buy
the side whose ask is at least X") also bought illiquid markets whose ask is
high only because the spread is wide; all five planned rules lost 8.5-13.3¢
per contract (t −27 to −56). **Extra variants, added after that run and
counted:** favourites chosen by the mid with a spread of at most 3¢ (80¢
and 90¢), momentum and reversal with a spread of at most 3¢, and a resting
(maker) order on the favourite side from the scan's own order rows. 10
variants in all.

- **Taker rules, corrected: none works after costs.** Favourite at mid 80¢+:
  −1.04¢ (t −7.3); 90¢+: −0.56¢ (t −4.0); momentum −0.99¢ (t −1.7, +0.15¢
  before fees); reversal −2.98¢ (t −5.2). Negative in both halves. The
  category ranked best on the earlier half never held on the later half.
- **Calibration** (realised YES rate minus the mid): long shots under 5¢
  are overpriced by 0.5¢ (t −3.3) and favourites at 90-95¢ underpriced by
  1.1¢ (t 2.4): a real favourite-longshot bias, but smaller than the spread
  plus the taker fee. Mid-priced YES at 35-50¢ is overpriced by 1.1¢
  (t −4.6), the region the current NO seller works in.
- **Correction, made before this entry was merged:** the first category
  labels read "GAS" inside soccer and golf names (LALIGASPREAD,
  BUNDESLIGASPREAD, PGASTROKEMARGIN), so two soccer spread series were
  counted as economics and drove that category's resting-order result
  (+1.51¢). With the labels fixed (sports checked first; tested):
- **Economic-data favourites** (rates, CPI, payrolls, jobless claims, stock
  indexes, metals, oil, natural gas): the favourite side is underpriced at
  the mid by 2.64¢ (t 4.61, 2,163 markets), but not by enough to trade on
  the quotes alone. Resting on it: +0.60¢ per filled contract (t 0.56, 820
  fills); buying at the ask with a spread of 3¢ or less: about 0 to +0.6¢
  (t 0.9 or less). The average spread on these favourites is 4.1¢ (median
  2¢), which absorbs the mispricing.
- **Resting on favourites everywhere:** −0.05¢ (t −0.27), and sports
  −0.25¢.

**Verdict:** no separate model-free strategy works across Kalshi's markets
on this data. The economic-data favourite mispricing is real at the mid
but too small to beat the spread with quotes alone; it would need a better
fair price from outside data (futures-implied rate odds, inflation
nowcasts, daily commodity prices) to be worth a dedicated study.

## 2026-10-22: Economic and financial markets priced from outside data (scope)

*A scope for the owner's decision, not yet a test plan. Each phase gets
its own written plan before it runs.*

**Why.** Across Kalshi, the favourite side of economic and financial
markets is underpriced at the mid by about 2.6¢ (t 4.6), but quotes alone
cannot capture it after the spread (entry above). A fair price from outside
data would let a strategy trade only where the favourite is clearly cheap.
That is a different strategy from v5: priced from financial data, not
sports, and taking or making on whichever side the outside price favours.

**Universe** (from the scan; sample volume is the scan's sample, not the
full market):

| Tier | Series | Events a year | Kalshi maker fee | Outside price |
|---|---|---|---|---|
| A, daily and weekly prices | S&P 500 (`KXINX`, `KXINXU`, `KXINXDUD`), Nasdaq-100 (`KXNASDAQDUD`), oil (`KXWTI`, `KXWTIW`), gold (`KXGOLDD`, `KXGOLDW`), silver (`KXSILVERD`), copper (`KXCOPPERD`, `KXCOPPERW`), natural gas (`KXNATGASD`, `KXNATGASW`) | about 250 per daily series | none (default) | price now plus implied volatility: the chance of finishing above a strike is a standard digital-option price (VIX, VXN, gold and oil volatility indexes are free daily; hourly prices needed) |
| A2, Treasury yields | `KX2YRRATEH` to `KX10YRRATEH` | daily | none listed | Treasury futures and yield volatility; liquidity rewards of about $4,300 open per series on 22 Oct |
| B, scheduled releases | CPI (`KXCPI`, `KXCPIYOY`, core), Fed (`KXFED`, `KXFEDDECISION`), payrolls, jobless claims, GDP, monthly gas (`KXAAAGASM`) | 8-52 | yes for CPI, Fed, payrolls, GDP, monthly gas (0.0175 × P × (1 − P), rounded up: 1¢ on a one-contract fill) | Cleveland Fed inflation nowcast (daily); Atlanta Fed Market Probability Tracker (daily, history downloadable); prior releases |

**What decides the order.** Tier B has few independent events (CPI and the
Fed about 20 a year together), so a backtest cannot tell a 2¢ edge from
luck for years, and maker fees eat thin edges on one-contract fills. Tier A
has hundreds of events a year per series, no maker fee and an
off-the-shelf pricing method, so it is the place to start. Tier A2 adds
liquidity rewards if quotes are large enough to count (target sizes of 100
to 20,000 contracts per side; our share decides the payout).

**Phases and gates.**
1. **Inventory (no new data, about a day).** For each Tier A series:
   settlement source and time, strike layout, spreads and volume by hour
   before expiry, fee status, open reward programs.
2. **Backtest (free data, about a week).** Kalshi's full public history for
   the shortlisted series (candles and trade prints, fetched like
   `research/backfill_kalshi.py`), hourly prices and daily volatility
   indexes. Fair value = digital-option probability, with one volatility
   scale fitted on the earlier half only. **Gate:** on the later half, log
   loss beats Kalshi's mid (paired, event-clustered t ≤ −2), and a replay
   (resting orders where the outside price says the favourite is cheap,
   one contract, first in line and at flow share 0.25) makes money after
   fees with t ≥ 2 on at least 300 events.
3. **Paper (two to four weeks).** The forward ledger in the
   `kalshi/paper_markets.py` style, with the outside price as the filter.
4. **Small live pilot,** only after paper passes: its own caps inside the
   shared account loss stops, separate from v5.

**Needs from the owner.**
- A way to download data: a GitHub workflow (a `.github/` change) or a
  script run on the server. The workspace cannot reach Kalshi or price
  feeds.
- Agreement that hourly price data from a free source is acceptable for
  research. Raw downloaded data would not be committed, only derived
  results.

**Risks.**
- These markets attract professional traders who already price from
  options, so the edge may be smaller than the quotes suggest.
- A price feed that is even minutes stale creates fake edge, so every
  timestamp has to be aligned.
- Tail outcomes (skew and fat tails) can make a simple volatility model
  misprice the far strikes in exactly the region where the mispricing
  appears.

## 2026-10-22: Strategy sweep across all scanned markets, with profit factor (exploratory plan)

*Written before running. Exploratory; nothing here changes the live rules.*

The owner asked for profitability and profit factor (winning dollars over
losing dollars) by market, and for more strategy types. Data: the scan's
hourly resting-order rows (`outputs/scan/orders_*.csv.gz`; one YES and one
NO order per market per hour, 7 to 4 hours before expected expiration, one
cent inside the spread when it allows, filled from public trade prints as
if first in line, held to settlement). Fees: Kalshi's default maker fee is
zero; the series on Kalshi's fee schedule with a maker multiplier pay
0.0175 × P × (1 − P) per contract (unrounded, a larger order).
`research/strategy_sweep.py`.

**Families (resting orders, one contract per hourly order):**
1. NO on every market; 2. YES on every market; 3. both sides at once
(market making); 4. the favourite side (price 80¢+); 5. the long-shot side
(price 20¢ or less); 6. NO where YES is 35-50¢ (the band that looked
overpriced across all markets); 7. both sides only where the spread is 5¢
or more; 8. NO only in hours with no trading in the previous hour, and
9. NO only in hours with trading. Nine families.

**Reported** for each family, overall and by category (sports, economics,
mentions, politics, entertainment, crypto, other): filled contracts, cents
per contract with event-clustered t, profit factor, total dollars, and the
earlier and later halves (split at the median date). Within each family,
series are ranked on the earlier half and the top 10 pooled on the later
half; a family or series is **promising** only if the later half makes
money with t ≥ 2 on at least 300 fills and the earlier half was also
positive.

## 2026-10-22: Strategy sweep across all scanned markets, with profit factor (results)

*Exploratory and simulated, run once as planned; `python -m
research.strategy_sweep`, tables in `outputs/research/strategy_sweep.md`.
202,805 markets; one contract per hourly resting order, first in line,
held to settlement. Profit factor (PF) = winning dollars / losing
dollars. Nothing here changes the live rules.*

| Family | Fills | ¢/contract (t) | PF | Earlier ¢ | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|
| 1 NO everywhere | 257,561 | +0.85 (6.7) | 1.05 | +1.09 | +0.59 (3.1) |
| 2 YES everywhere | 136,330 | −1.41 (−8.5) | 0.93 | −0.92 | −1.85 (−8.0) |
| 3 both sides | 393,891 | +0.07 (1.1) | 1.01 | +0.44 | −0.31 (−3.7) |
| 4 favourite side | 63,393 | +0.55 (3.0) | 1.06 | +0.88 | +0.28 (1.2) |
| 5 long-shot side | 54,900 | −0.54 (−3.0) | 0.94 | +0.02 | −0.93 (−4.2) |
| 6 NO, YES 35-50¢ | 58,256 | +0.76 (2.5) | 1.03 | +0.83 | +0.67 (1.5) |
| **7 both sides, spread 5¢+** | **76,694** | **+2.44 (15.9)** | **1.22** | **+3.07** | **+1.70 (7.8)** |
| 8 NO after a quiet hour | 59,944 | +0.27 (1.3) | 1.02 | +0.80 | −0.27 (−0.9) |
| 9 NO after a traded hour | 141,022 | +0.86 (5.6) | 1.05 | +0.97 | +0.73 (3.1) |

- **Economic and financial markets: no edge from quotes alone.** NO
  everywhere +2.46¢ (PF 1.20) but +0.38¢ on the later half (t 0.2); YES
  everywhere −6.04¢ (PF 0.59); both sides −1.51¢; both sides in wide
  spreads +0.27¢.
- **Family 7, two-sided quotes in wide-spread markets, is the one
  different strategy that held up.** Post a YES bid and a NO bid one cent
  inside a spread of 5¢ or more, hold whatever fills to settlement.
  - Positive in both halves, and broad: 1,179 series, of which 369 have
    enough data; 249 were positive, 72 had t ≥ 2 against 10 with t ≤ −2,
    and 67 survived a 10% false-discovery-rate correction. The top 10
    series supply only 15% of the profit. Sports +2.74¢ (PF 1.23),
    esports and other +1.28¢, mentions +3.36¢; economics +0.27¢.
  - Where the money comes from: 21% of filled hours filled both sides,
    locking in the spread less 2¢ (9.7¢ a pair on an average 11.7¢
    spread). That gave $1,303 of the $1,873. One-sided fills made +1.14¢
    (t 4.9).
  - It grows with the spread: 5-8¢ +0.71¢ (PF 1.07); 8-15¢ +1.44¢
    (PF 1.12); 15-30¢ +4.60¢ (PF 1.38); 30¢+ +8.44¢ (PF 1.82).
  - Capacity: a median of 86 contracts traded through a filled order's
    price in its hour (quartiles 18 and 375).
  - **Caveats.** In-sample (the 5¢ threshold was chosen with the family);
    fills are read from trade prints, so a wide-spread market's few
    prints decide everything. Other bots may now quote inside those
    spreads. Holding both sides needs about a dollar of capital per pair
    until settlement.
- Families 1 and 9 (NO everywhere) also held on the later half, but they
  are v5's idea applied everywhere, and their top-10 series did not hold.

**What carries forward:** family 7 deserves a written forward paper test
(two-sided quotes one cent inside, spreads of 8¢ or more, the scan's
sports, esports and mentions series), scored from public trade prints in
the `kalshi/paper_markets.py` style, before anything live.

### Addendum: hedging versus holding (exploratory, 2 extra variants)

Same rows, spreads of 8¢ or more, one contract per order (simulated,
in-sample). (A) Hold every fill to settlement: +3.91¢ per contract
(PF 1.33), $1,625, daily sd $7.14, worst day −$14.8. (B) When only one
side fills, sell it back at the market an hour later (taker, paying the
fee): +0.22¢ (PF 1.03), $91, daily sd $3.74, worst day −$21.2. Exiting
pays the wide spread the strategy is trying to earn; one-sided fills
averaged +5.0¢ held and −4.6¢ sold. (C) Hold, but stop quoting a side once
one contract is held in that market: +3.60¢ (PF 1.30), $1,219 (−25%),
daily sd $5.10 (−29%), worst day −$14.7. About the same profit per unit of
risk as (A). Hold to settlement, with a per-market inventory cap as a risk
control once sizes grow.

## 2026-10-22: Spread maker pilot, shadow and small live (plan)

*Written before the code. Requested by the owner on 22 October ("we need to
seriously start building this spread bot ... push to live"); defaults
chosen by the owner's "no preference" answers. Evidence: the strategy
sweep above (family 7), simulated and in-sample.*

**Strategy `spread-maker-v1`.** In the allowed series (below), for open
markets whose expected expiration is 4 to 7 hours away and whose spread is
8¢ or more: rest a YES bid one cent above the best YES bid and a NO bid one
cent above the best NO bid, one contract each, post-only, each order
expiring after 65 minutes; re-quote when the book moves. Hold fills to
settlement. Do not quote a side once one contract of that side is held in
the market (net).

**Universe.** The 66 series that passed the 10% false-discovery check at
8¢ (strategy sweep), minus `KXNBAPTS` and `KXNFLRECYDS` (traded by v5 and
the NFL bot); never a ticker in another bot's journal; never a series that
pays a maker fee on Kalshi's schedule.

**Two modes, one worker** (`live/prod_spread_auto.py`):
- **Shadow** (default, no orders): every 10 minutes, write the quotes it
  would post on every eligible market (at most one per market and side per
  hour, as in the backtest), then score them from Kalshi's public trade
  prints and results with the backtest's fill rule.
- **Live** (only with `SPREAD_AUTO_ARM=YES` and the owner-created marker
  `/etc/market-maker-spread.enabled`): the same quotes as real orders,
  within the caps below. The shadow ledger keeps running beside it, so live
  fills can be compared with shadow fills on the same markets.

**Risk limits (old → new, why).**
- New, spread bot only: 1 contract per order; at most 1 net contract per
  market and side; $25 of open exposure (resting orders plus held
  contracts at cost); 20 orders per pass and 300 a day; a $5 daily and $15
  total realized-loss stop of its own. Why: a pilot sized so the worst
  plausible week costs less than v5's daily stop.
- Account-wide realized-loss stops: −$20 a day and −$60 total, unchanged
  in size, now counting the spread bot's settled markets as well as NBA
  and NFL (old scope: NBA + NFL markets). Why: the owner chose one stop for
  the whole $350 account.
- NBA and NFL caps (`LIMITS`: $2,050 lifetime, $180 daily, $165 active)
  unchanged and still computed from NBA and NFL orders only; the spread
  bot's orders count against its own $25 instead. Total open exposure of
  all three is therefore at most $190.
- `live/shared_account_risk.py` learns a third cohort: the NBA and NFL
  workers recognise the spread bot's orders, fills and positions (YES or
  NO, net per market, never more than it ordered) instead of halting on
  them, and still halt on anything unowned.

**Failure handling.** Journal before every order and cancel. A placement
the exchange rejects with an HTTP 4xx (for example a post-only order that
would cross) is recorded as rejected only after a signed read confirms no
order with that client id exists; any other failure is an unknown outcome
that halts all three bots until the owner reconciles it, as today. A `KILL`
file cancels the spread bot's resting orders.

**What will be measured and when.**
- **Shadow, after 2 weeks:** profit per filled contract from the shadow
  ledger at flow share 0.25, with at least 300 fills. Pass: above zero.
- **Live, after 300 filled contracts or 4 weeks, whichever comes first:**
  live profit per filled contract (event-clustered t) and the live fill
  rate against the shadow fill rate on the same markets. Continue if live
  profit per contract is above zero; stop and review if the $15 total stop
  is hit or live fills are less than half the shadow's. No size increase
  before that review.

## 2026-10-22: Spread maker pilot (implementation notes)

*Added after the code, to record choices the plan above left open. Nothing
in the plan's strategy, limits or pass/fail bars changed.*

- **Prices come from the order book without our own quotes.** Once our
  quotes rest, Kalshi's listed best bid and offer are often ours; pricing
  off them would make the bot chase itself one cent at a time, and on an
  8¢ market our own quotes would shrink the listed spread to 6¢ and switch
  it off. For any market where the bot already rests quotes, it reads the
  public order book and removes its own orders before applying the rule.
  The backtest used other traders' prices only, so this is the faithful
  version of the rule.
- **Re-quoting.** A resting quote is cancelled and replaced when its price
  is no longer the rule's price, or after 60 minutes (orders expire on the
  exchange at 65). Quotes are pulled when a market drops out of the 4–7 hour
  window, its spread falls below 8¢, or its book cannot be read. Each new
  quote is checked against a fresh book read just before it is sent.
- **Series.** The 64 series in `live/spread_policy.py` (the 66 minus
  `KXNBAPTS` and `KXNFLRECYDS`), plus a block on every ticker prefix the
  NBA and NFL bots trade.
- **Shadow fill rule** (same as the backtest): a YES quote at p counts
  contracts sold by takers at p or below during its hour; a NO quote at q
  counts YES contracts bought at 1 − q or above. Block trades are ignored.
  Shadow quotes ignore the live inventory cap, as the backtest did.
- **Shared stops cut both ways.** Spread losses count toward the account's
  −$20 daily and −$60 total stops, so a bad spread day can stop the NBA and
  NFL bots too (and the reverse). The spread bot's own $5 and $15 stops
  usually trigger first.
- **Realized P&L comes from the bot's own fills**, not settlement records
  (found by the independent review): Kalshi nets YES against NO, so a closed
  pair (profitable or not) never reaches a settlement record. Fills are
  matched first in, first out per market; a pair realizes when its second
  leg fills, a held contract at settlement. This is the number both loss
  stops use and the live result the pilot reports.
- The private fills export and the public P&L page do not yet include the
  spread bot; until they do, live spread results are on the server only
  (`--status`).

## 2026-10-22: Spread maker pilot, 5 contracts per order (plan amendment)

*Written before the code change and before any live spread order. The
owner chose 5 contracts per order on 22 October ("i want to do 5
contracts") after seeing the sizing simulation below. Nothing else in the
plan changes: same markets, quotes, window, failure handling and
pass/fail bars.*

**Limits (old → new).** Contracts per order 1 → 5. Net contracts per
market and side 1 → 5 (an order shrinks so held plus resting never goes
past 5). Open exposure $25 → $60. Own realized-loss stop −$5 → −$10 a day
and −$15 → −$40 in total. Unchanged: 20 orders per pass, 300 a day, and
the account stops (−$20 a day, −$60 in total, all three bots). Why: at 5
contracts a $25 cap is full most of the time, and in the simulation the old
stops would have paused the bot on about 14 ordinary days a year and could
be reached by an ordinary drawdown (worst −$18). With these limits all three
bots together can have at most $225 open on the $350 account (NBA $150, NFL
$15, spread $60). A −$10 spread day leaves NBA $10 of the shared daily stop.

**Sizing simulation (exploratory, simulated, in-sample; about 20
variants: 1, 2, 5 and 10 contracts × flow share 1 and 0.25 × open caps).**
Scan rows for the 64 pilot series, 8¢+ spreads, 4–7 hours before expected
expiration, 24,768 two-sided market-hours, Sep 2025 – Aug 2026; fills =
min(contracts traded through our price, order size), binomial at flow
share 0.25; per-market net cap = order size; held to settlement.

| Setup (flow share 0.25) | $/month | ¢/contract (t) | Worst day | Days ≤ −$5 | Worst drawdown |
|---|---:|---:|---:|---:|---:|
| 1 contract, $25 open | 53 | 7.2 (20.4) | −$4.0 | 0 | −$4.0 |
| 5 contracts, $25 open | 136 | 6.7 (14.5) | −$11.7 | 11 | −$16.4 |
| 5 contracts, $60 open | 185 | 6.5 (16.5) | −$15.8 | 14 | −$17.9 |
| 5 contracts, no cap | 204 | 6.1 (16.9) | −$20.7 | 12 | −$20.7 |

Caveats: the 64 series were selected on this same data (across all
wide-spread markets the edge was 3.9¢ a contract, not 6–7¢), so expect
less; months ranged from $3 to $353; fills come from trade prints. Larger
orders earn a little less per contract (6.5¢ against 7.2¢), consistent
with bigger orders filling more when the market moves against them.

**What changes in measurement.** Live and shadow profit are reported per
contract and in dollars at 5 contracts; the shadow ledger scores a
5-contract quote as min(contracts traded through, 5) first in line and as
the expected fill at flow share 0.25. The live review after 300 filled
contracts or 4 weeks now comes sooner; its bars are unchanged.

## 2026-10-22: Spread maker live fill share (plan amendment)

*An amendment, written after the pilot went live (first orders 22:33 UTC)
and before any live order window was scored. The plan compared the live
fill rate with the shadow fill rate; this replaces that with a
contract-weighted comparison on the live orders' own resting windows,
because the shadow quotes and the live orders are not the same orders. The
bar keeps its meaning (half of what first-in-line fills would have been).
Revised after an independent review the same night; no strategy or limit
changes.*

- **Window.** Each accepted live order rests from the exchange's
  acceptance until 65 minutes after it was sent or until its cancel was
  confirmed, whichever is sooner (the reply times are used when they fall
  within 5 minutes of the pass that sent them; otherwise the pass's start
  time). It is scored once, at least 5 minutes after the window ends, and
  only right after a live pass has copied the exchange's fills into the
  journal, so every scored window's fills are already there.
- **Through.** Contracts in Kalshi's public trade prints, on the order's
  ticker during its window, at or through its price on its side (the
  shadow ledger's rule). First in line, the order would have filled
  min(through, order size).
- **Live fill share** = Σ min(contracts we filled, min(through, size)) /
  Σ min(through, size), over all scored orders, one row per order. 1.0 is
  the backtest's first-in-line assumption. Our own fills appear in the
  prints, so they count in both.
- **Cautious benchmark.** The replays' cautious case gives each traded
  contract a 0.25 chance of reaching us. That is not a fill share of 0.25:
  with 86 contracts through (the sweep's median) a 5-contract order almost
  surely fills. So the same formula is also computed with the replay's
  expected fill, E[min(Binomial(through, 0.25), size)], in place of ours
  (`cautious_replay_share`). A live share below it means even the cautious
  replay overstated fills.
- **How the bar is read.** "Live fills less than half the shadow's" at the
  checkpoint means a live fill share below 0.5.
- **Also reported:** orders scored, orders with any contract traded
  through, and how many of those got any fill.
- **Limits.** Scoring reads public prints only, one attempt per read, at
  most 10 markets a pass in shuffled order, and starts no new market 150
  seconds after the worker started (waiting for the account lock
  included); unscored windows wait for a later pass. A print without a
  usable size counts for nothing.
- **Where.** `live/prod_spread_auto.py` (`live_windows`,
  `score_live_windows`, `fill_share`), the server's `--status`, the
  private export's `markets.spread.live_fill_share`, and
  `python -m research.live_checkpoint`, which applies the plan's bars.

## 2026-10-22: Spread maker, a series that pays a maker fee (owner decision)

*Operational record. No change to the code or the bars.*

The plan says never to quote a series that pays a maker fee. The bot's
own fills on 22 October showed that Kalshi charges one on `KXNCAAFSPREAD`
(college football spreads): 0.0175 × contracts × price × (1 − price), at
most about 0.44¢ a contract. The bot's maker-fee list
(`live/spread_policy.py`, checked 22 October) did not include it. The owner
chose to keep trading the series. The fees are subtracted in the bot's
realized P&L, which its loss stops and the checkpoint use.

## 2026-10-23: Spread maker v2, pregame only (plan amendment)

*Written before the code is deployed. The owner paused the spread maker on
the night of 22 October and approved this change ("Yes get it live
again") after the exploratory split below. Strategy version
`spread-maker-v2-pregame`.*

**Why.** On its first night (22 October), v1 quoted a college football
market about 33 minutes after kickoff, and esports orders posted minutes
before a match rested into it. v1's 4–7-hour window counts from Kalshi's
expected expiration, which for that football game was 6 hours after
kickoff. A resting order in a live event is filled mostly when the game
has moved against it.

**New rules (v1 had none of these; limits and pass/fail bars unchanged).**
Revised after an independent review the same night (before deployment):
the margins doubled to cover the 10-minute timer, milestones are trusted
by type and only when never late, and v2's expected share of profit is
stated for its actual rule.
- A market is quoted only when its event's scheduled start is known. The
  first source is the time written in the event ticker (New York time;
  for example `KXR6GAME-26OCT222000...` is 20:00; a time the clock change
  skips or repeats takes the earlier instant).
- The second source is Kalshi's milestones (`GET /milestones`, starts
  within 12 hours before the market's expected expiration). For events
  whose ticker carries a time, up to 4 a pass (one per series, rotating)
  are compared with their milestones; an earlier milestone also moves that
  event's start earlier. For events without a time, a milestone start is
  used only if its milestone type (for example `basketball_game`) has
  matched ticker times on at least 2 different events (from 15 minutes
  earlier to 2 minutes later) and was never more than 2 minutes later than
  a ticker time in the last 2 days. Otherwise the event has no known start
  and is not quoted.
- A new quote needs the start at least 85 minutes away (its 65-minute life
  plus 20 minutes), and its exchange expiry is capped at 20 minutes before
  the start. Every resting quote is cancelled once the start is 20 minutes
  away or less (twice the timer period, so a start learned late is still
  caught), including when its order book cannot be read and v1 orders with
  no recorded start.
- The shadow ledger follows the same rule. The live fill share is measured
  on v2 orders only.

**Evidence (exploratory; SIMULATED, in-sample, first in line, one contract
per order, the 64 pilot series, spreads of 8¢ or more; 7 variants and 2
splits tried, one variant by the reviewer;
`python -m research.spread_pregame_split`).**
- Where the event ticker carries the start (30% of fills): orders resting
  wholly before the start made +9.9¢ per contract (t 9.9, 2,285 fills, 85%
  of those series' profit); orders across the start +5.1¢; in the game
  +2.7¢ (t 2.3).
- Every series, by hour: the last hour before the 4-hour cutoff, when
  events often start, made +6.4¢; the hours before it +9.1¢ to +11.9¢.

| Rule | Fills | ¢/contract (t) | Earlier / later half | Share of profit |
|---|---:|---:|---:|---:|
| All hours (v1) | 11,263 | +8.45 (21.5) | +9.1 / +7.8 | 100% |
| Skip the last hour | 5,930 | +10.27 (18.2) | +10.9 / +9.6 | 64% |
| Ticker start known, pregame only | 2,285 | +9.87 (9.9) | +12.2 / +7.5 | 24% |
| **Ticker start known, v2 rule (posted 85+ minutes before)** | 1,474 | **+10.54 (8.7)** | +12.5 / +8.6 | **16%** |

With ticker times alone, v2 keeps about 16% of v1's simulated profit at a
higher +10.5¢ per contract (the reviewer's 75-minute version: 1,493 fills,
+10.55¢). Milestones add events without a ticker time where their type is
trusted; how much cannot be computed from this data, which has no start
times for those series. The 64% "skip the last hour" row is not an upper
bound for v2: it includes in-game hours in series whose expiration is long
after the start, such as college football, which v2 can never quote (its
window opens only an hour before kickoff, and v2 needs 85 minutes). Scaled from the sizing amendment's simulated
$185 a month (5 contracts, flow share 0.25), ticker-only v2 would be
roughly $30 a month; treat that as an order of magnitude, not a forecast.

**Measurement.** v2 is judged on its own orders (`research.live_checkpoint`
filters by strategy version): 300 filled contracts or 4 weeks from its
first order, with the same bars. v1's 27 orders and 13.4 filled contracts
are reported apart and not judged; the shadow ledger's simulated summary
still pools both versions. Exports gain each order's recorded start and
minutes before it.

## 2026-10-23: Spread maker queue position and markouts (measurement plan)

*Written before the code and before any reading; revised twice after
independent review, still before any reading. The owner asked for it on 23
October after asking how the bot could be first in line and what its
10-minute update cycle costs. Measurement only: no change to the rules,
limits or pass/fail bars. v2 orders only.*

**Questions.** (1) How often does another trader get ahead of the spread
maker's quotes between its passes? (2) Are its fills picked off: does the
price move against a fill soon after it, as it would if stale quotes are
being hit by better-informed traders?

**Why not Kalshi's queue position.** The bot re-quotes, at the start of each
pass, any order that another bid has matched or beaten (it prices from the
order book with its own orders taken out). An order that survives a pass is
therefore alone at the best price, so reading its queue position would say
"nothing ahead" by construction. The useful reading is the state of the
book *before* that pass's re-quotes.

**Method.**
- **Standing.** At the start of each live pass, before any re-quote, for
  each resting order whose book was read (own orders taken out): is
  another bid on its side better (*outbid*: someone is ahead of it),
  equal (*joined*: behind it in time), or not (*alone*)? One line per pass
  with the counts. No extra requests: the book is already read. An outbid
  order is then re-quoted, so this is a rate per 10-minute pass (how often
  someone got ahead within one pass), not per order; orders whose book
  could not be read are not counted.
- **Markouts.** For each fill, the market 10, 30 and 60 minutes later,
  read at the first pass after each horizon (at most 12 minutes late, else
  recorded as missed) from the public listing taken at the start of that
  pass, from the side bought, in cents:
  - *adverse move*: the side's midpoint then minus its midpoint when the
    quote was posted (the quote sat one cent above the best bid of the
    recorded spread); below 0 means the price moved against the fill;
  - *realized spread*: the midpoint then minus the price paid and the
    fill's own fee per contract (it includes the half-spread earned at
    entry);
  - *exit move*: the side's best bid then minus the price paid, left empty
    when that best bid was the bot's own quote resting at the start of the
    pass.
  The listing includes the bot's own quotes, one cent inside each side, so
  a midpoint is within half a cent of the market's. Each record stores the
  contracts filled and the minutes to the event's start.
- **What is summarised.** Readings taken before the event starts, weighted
  by contracts, for all fills and for one-sided fills (no opposite-side
  fill in the same market in the 60 minutes *before* it: a later opposite
  fill is often caused by the price moving, so looking ahead would bias the
  one-sided group toward fills that went badly). Late or missing readings
  and readings after the start are counted apart, as are fills that were
  never measured (for example while the bot was disarmed) and fills
  without a fee record (counted at fee 0). The bot writes the
  summary each pass (`measurements_summary.json`); `--status` and the
  private export show it.

**How the readings will be used (decided now), once, at the spread
maker's checkpoint (300 filled contracts or 4 weeks), not before.**
`--status` is for watching the bot, not for deciding.
- **Picked off:** if the 30-minute realized spread after fees on one-sided
  fills observed before the start averages 0¢ or less, adverse moves are
  eating the edge. Then a separate written plan will test a faster cancel
  loop (checking markets with resting quotes every 1–2 minutes). The
  30-minute adverse move, the all-fills figures and event-clustered t
  statistics (contract-weighted, computed in the summary) are reported
  with it; at 300 contracts this is a go/no-go reading, not a significance
  test.
- **Standing:** if the bot is outbid in more than a quarter of at least
  200 order checks (each check is one 10-minute pass) and the live fill
  share is below 0.5, other traders often get ahead of it between passes;
  a separate written plan would then test re-quoting faster in markets
  where it rests.

## 2026-10-23: NBA rules v6, three contracts per order, and −$100 total stops (plan amendment)

*Written before the code change and before any v6 order. On 23 October
the owner chose more risk on the strategy with the most live volume ("we
have to put on risk"): 3 contracts per NBA order, a −$100 account-wide
total stop, and a smaller minimum spread for the spread maker. The last
was dropped after the replay below; the owner chose to keep 8¢.*

**Limits (old → new).**
- NBA contracts per order: 1 → 3 (`MAX_CONTRACTS`). Order selection,
  pricing, the 0–15¢ edge band, the 2–6 hour window and every veto are
  unchanged; only size changes.
- NBA per-game submissions: $25 → $50 (`MAX_GAME_COST`). At 3× the
  v5 orders of 21–22 October, 3 of 13 games would have passed $25 and 1
  would have passed $50.
- NBA lifetime submitted allowance: $2,000 → $5,000 (`MAX_GROSS_COST`),
  and the shared lifetime cap $2,050 → $5,050 (NBA plus NFL's $50). At 3×,
  $2,000 would last about 18 nights.
- NBA's own total realized-loss stop: −$60 → −$100
  (`MAX_REALIZED_CUMULATIVE_LOSS`). The owner raised the account-wide
  stop to give room for 3× swings, and NBA's own stop must move with it,
  otherwise NBA alone still stops at −$60.
- Account-wide total realized-loss stop (all three bots): −$60 → −$100
  (`ACCOUNT_LOSS_STOPS["cumulative"]`).
- Unchanged: the −$20 daily stops (NBA's and the account's), NBA's $150
  open and $150 daily caps, the $25 per-team cap, $4 per order, 40 orders
  per game, NFL, and every spread maker limit. At 3×, v5's busiest night
  (21 October, 11 games) would have reserved $145 of the $150 daily cap, so
  that cap now limits the largest slates. All bots together can still have
  at most $225 open on the $350 account.

**Why.** Live v5 so far (78 settled fills, 21–22 October, live): +4.3¢ per
contract, t 0.77 clustered by game. Public trade prints show a median of
over 300 contracts traded at or through the price of each filled order
while it rested, and 88% had at least 5, so trading volume does not limit
a 3-contract order; the caps do. In the 2025–26 replay (simulated,
in-sample) profit per contract barely changes between 1 and 10 contracts
per order (3.61¢ and 3.64¢ at flow share 0.25), and the worst drawdown
grows about $20 per contract of order size, which −$100 covers at 3.

**Version and checkpoint.** New orders carry `nba-no-v6-three-contracts`;
v5 joins the prior versions whose resting orders are left to expire (new
orders wait for them, as in earlier transitions). The NBA review keeps its
bars, judged on v5 and v6 together because the selection rule is the same:
- **1,900 settled filled orders** (counted as orders, not contracts; at one
  contract per order the two were the same), **the $5,000 allowance** (was
  $2,000) or **30 days from the first v5 order**, whichever comes first;
- profit per contract, after fees, with t clustered by game; verdict rules
  unchanged. v5 and v6 are also reported separately. If v6's profit per
  contract is clearly below v5's, the owner reviews before the checkpoint.

**Spread maker minimum spread, 8¢ → 6¢: not adopted (exploratory replay,
simulated, in-sample, first in line, 1 contract; 2 variants plus one slice).**
`research/spread_pregame_split.py` with the v2 rule (start known from the
ticker, posted at least 85 minutes before it), 64 pilot series:

| Minimum spread | Fills | ¢ per contract (t) | Simulated $ |
|---|---:|---:|---:|
| 8¢ (live) | 1,474 | +10.54 (8.67) | +155.35 |
| 6¢ | 2,100 | +7.10 (7.13) | +149.07 |
| 6–7¢ spreads alone | 626 | −1.00 (−0.67); later half −3.56 | −6.28 |

The extra 42% of fills earned nothing: at 6–7¢ the two cents given up to
bid inside, plus the drift after one side fills, take the whole gap. The
owner kept 8¢. Other ways to more pregame fills (quoting earlier before the
start, more series with known starts) need their own written test.

## 2026-10-23: NBA v6 replays before go-live (exploratory)

*Run after the plan amendment above and before any v6 order; the plan's
text is unchanged.*

**Replay of v5 against v6 (exploratory, simulated, in-sample; 3 rule sets ×
2 flow shares; `python -m research.nba_v6_replay`).** The owner asked to see
it before go-live. Live caps applied in placement order, loss stops per
night; cautious = flow share 0.25, median of 20 draws.

| Rules | P&L | ¢ per contract (t) | Filled orders / contracts | Worst night | Max drawdown | Daily stops |
|---|---:|---:|---:|---:|---:|---:|
| v5, until $2,000 is placed (49 nights) | +$41.78 | 2.22 (1.41) | 1,884 / 1,884 | −$7.56 | −$10.02 | 0 |
| v6, until $5,000 is placed (53 nights) | +$167.27 | 3.55 (2.22) | 1,619 / 4,713 | −$23.37 | −$38.66 | 1 |
| v6, cautious | +$146.45 | 3.44 (2.12) | 1,515 / 4,233 | −$24.38 | −$36.37 | 1 |
| v6, whole season, no allowance | +$953.69 | 3.89 (5.56) | 8,408 / 24,536 | −$23.37 | −$69.89 | 2 |
| v6, whole season, cautious | +$847.28 | 3.75 (5.22) | 7,938 / 22,641 | −$24.38 | −$78.54 | 2 |

At three contracts the $150 nightly and $50 per-game caps bind, so the
lowest-edge orders are dropped first: fewer separate orders (1,619 against
1,884) but more profit per contract. The −$100 total stop was never hit (0
of 20 cautious draws). These are the season's first weeks, which were weak
(2.2¢ against 3.9¢ over the whole season); fills are optimistic.

**Larger sizes, whole season (exploratory, simulated, in-sample; 4 rule
sets × 2 flow shares, no lifetime allowance, −$20/−$100 stops).** Asked by
the owner ("can we push it even more?"); first in line / cautious median of
20 draws:

| Setup | Season P&L | First 30 nights | ¢ per contract | Worst night | Max drawdown | Daily stops |
|---|---:|---:|---:|---:|---:|---:|
| 3 contracts, $50/game, $150/night (v6) | $954 / $847 | $13 / $9 | 3.9 | −$24 | −$70 / −$79 | 2 |
| 5 contracts, $75/game, $150/night | $955 / $833 | $35 / $31 | 3.6 | −$35 | −$97 / −$99 | 8 |
| 5 contracts, $75/game, $250/night | $1,469 / $1,285 | $45 / $41 | 3.9 | −$39 | −$90 / −$106 | 10–11 |
| 10 contracts, $150/game, $250/night | $1,244 / $1,224 | $33 / $35 | 3.1 | −$66 | −$143 / −$147 | 21–24 |

The nightly cap, not the order size, limits profit: 5 contracts at $150 a
night earns no more than 3, and 10 contracts earns less than 5 because the
larger orders crowd out the best ones. 5 contracts at $250 a night is the
next step, but its drawdowns reach the −$100 stop and $250 a night plus the
other bots' $75 nearly fills the $350 account; it needs more capital or
live evidence first. Not adopted.

## 2026-10-23: Spread maker, more pregame fills: start times per series and earlier quoting (plan)

*Written before the scan below runs; no data from it has been seen. The owner
asked for many more spread maker fills (23 October) without going back to
quoting during live events.*

**Why.** v2 quotes only markets whose event start is known, at least 85
minutes ahead, 4–7 hours before Kalshi's expected expiration. In the 64
pilot series (simulated, in-sample, 8¢+ spreads, 4–7 hours), 7,839 of 11,263
fills (70%, +8.8¢ a contract, all hours) were in 55 series whose event
tickers carry no start time, so v2 skips them; only 24 series carry one.
Live, 95 of v2's first 110 orders were CS2.

**Question.** Can the spread maker quote more markets before their events
start, by knowing more start times and by quoting earlier than 7 hours
before expiry, while keeping a positive edge?

**Data.** A new scan (`scan.yml`, window `24,4`, written to
`outputs/scan_24h`): the 64 pilot series, up to 400 sampled settled markets
each from the last 400 days, hourly quotes 24 to 4 hours before expected
expiration, trade prints, and each event's Kalshi milestones and ticker
start. Orders and fills as in the pilot's replay: both sides one cent inside
spreads of 8¢ or more, one contract, first in line (flow share 1) and flow
share 0.25, held to settlement, maker fee as in the sweep.

**Start-time sources.**
- *S1, ticker:* the time written in the event ticker (as v2).
- *S2, milestone:* the earliest of the event's milestones that start within
  12 hours before expiry (as v2 reads them live), by milestone type. A type
  is used only if, on events that also have a ticker start, its start is
  within 15 minutes before to 2 minutes after the ticker's in at least 95% of
  at least 20 such events.
- *S3, per-series offset:* for a series whose events have S1 or S2 starts,
  the median of (expiry − start) if the middle half of that gap spans 30
  minutes or less; then start = expiry − median − 30 minutes. Used only for
  events without S1 or S2.

**Pregame rule** (unchanged from v2): a quote counts if it was posted at
least 85 minutes before the start; anything later, or with no start, is not
quoted.

**Variants (9 rules × 2 flow shares = 18 runs).** Windows 7→4 (today), 12→4
and 24→4 hours before expiry × start sources S1 (today), S1+S2 and
S1+S2+S3. The baseline is 7→4 with S1, which is v2.

**Pass bar (judged once on this scan).** A variant may become v3 only if:
1. it has at least 2× the baseline's pregame fills;
2. the fills it adds beyond the baseline earn a positive profit per contract
   with event-clustered t ≥ 2 at flow share 1, and are positive at flow share
   0.25;
3. those added fills are positive in both halves of the sample (by date);
4. no single series supplies more than a quarter of the added profit.

If several pass, the one with the most added fills is proposed as v3, with
its start-time table and window, through a reviewed PR. If none pass, v2
stays and the result is recorded here.

**Known limits.** The 64 series were chosen on earlier data from these
markets (in-sample); fills assume first in line; live, S2 and S3 need the
same inputs in real time (the bot already reads milestones; S3 would ship as
a table in the code).

## 2026-10-23: Spread maker, more pregame fills: results (pre-registered)

*Plan: "2026-10-23: Spread maker, more pregame fills: start times per series
and earlier quoting (plan)". Scan run 39964969563 (`outputs/scan_24h`), all 64
pilot series, 11,263 sampled events, 10,883 with Kalshi milestones;
`python -m research.spread_start_window`. Simulated, in-sample, one contract,
8¢+ spreads; implementation detail not in the plan: S3 needs at least 10
known starts in a series.*

| Rule (hours before expiry, start sources) | Pregame fills | ¢ per contract (t) | Halves ¢ | Flow 0.25 fills | Added fills, ¢ (t) | Bar |
|---|---:|---:|---:|---:|---:|---|
| 7→4, S1 (v2, baseline) | 1,152 | 10.20 (7.26) | 10.85 / 8.99 | 1,020 | — | — |
| 12→4, S1 | 2,403 | 8.94 (7.68) | 9.82 / 7.49 | 2,109 | 1,251, 7.77 (5.14) | pass |
| 24→4, S1 | 4,328 | 8.70 (9.08) | 10.33 / 6.47 | 3,718 | 3,176, 8.15 (7.60) | pass |
| 7→4, S1+S2 | 2,235 | 10.81 (10.85) | 11.44 / 8.70 | 1,987 | 1,083, 11.45 (8.07) | fail (under 2× fills) |
| 12→4, S1+S2 | 4,985 | 9.42 (11.58) | 10.10 / 7.12 | 4,388 | 3,833, 9.18 (10.08) | pass |
| 24→4, S1+S2 | 8,899 | 9.26 (13.40) | 10.34 / 6.16 | 7,639 | 7,747, 9.12 (12.44) | pass |
| 7→4, S1+S2+S3 | 2,321 | 11.04 (11.34) | 11.75 / 8.61 | 2,066 | 1,169, 11.87 (8.74) | pass |
| 12→4, S1+S2+S3 | 5,278 | 9.34 (11.85) | 10.03 / 6.89 | 4,641 | 4,126, 9.10 (10.39) | pass |
| **24→4, S1+S2+S3** | **10,223** | **8.69 (13.84)** | 9.53 / 5.86 | 8,846 (8.22¢) | **9,071, 8.50 (12.92)** | **pass** |

**Result.** The plan's choice, the passing rule with the most added fills, is
24→4 hours with all three start sources: 8.9× the baseline's pregame fills,
added fills +8.50¢ a contract (t 12.92), positive in both halves (9.40¢ /
5.21¢), +8.22¢ at flow share 0.25, and no series over 12% of the added
profit. Quoting earlier with ticker starts alone gives 3.8×.

**Milestone types (S2 check, start within −15 to +2 minutes of the ticker's
on ≥95% of ≥20 events).** Trusted: baseball_game (99.4% of 1,144),
hockey_tournament (99.8% of 431), basketball_game (97.0% of 396), cricket_match
(96.2% of 314), one_off_milestone (95.0% of 381). Not trusted:
**esports_match (38% of 1,451)**: its start is later than the ticker's by more
than 2 minutes in 51% of events (median +10 minutes, 90th percentile +60), so
an esports event with no ticker start must never be quoted from its milestone.
Live v2 trusts milestone types dynamically (two matches, never late in two
days), which can briefly trust esports_match; v3 should block it.

**Caveats.** In-sample (the 64 series were chosen on earlier data from these
markets), first-in-line fills, one contract, and no open-exposure cap: live,
the $60 cap and 5-contract orders limit how many markets can be quoted at
once. The later half is weaker (about 5–6¢ against 9–10¢). Live v3 would need
the window, a fixed list of trusted milestone types and the per-series offset
table, through a reviewed plan amendment.

## 2026-10-23: Spread maker v3: quote from 24 hours, more start times, 2 contracts (plan amendment)

*Written before the code change and before any v3 order. It applies the
rule chosen by the pre-registered study above (24→4 hours, start sources
S1+S2+S3). The owner chose smaller orders across more markets on 23 October
("Smaller orders, more markets").*

**Rules and limits (old → new).**
- Window: 4–7 → **4–24 hours** before Kalshi's expected expiration
  (`WINDOW_HOURS`). The pregame rule is unchanged: a new quote needs a known
  start at least 85 minutes away, and every quote is cancelled 20 minutes
  before it.
- Start times, in order:
  - the ticker's (unchanged);
  - a Kalshi milestone of a **research-validated type**: baseball_game,
    basketball_game, cricket_match, hockey_tournament and one_off_milestone.
    Each matched ticker starts on 95% or more of at least 314 events. A
    live observation of one of these starting more than 2 minutes after a
    ticker time still revokes that type for 2 days. **esports_match is
    never trusted.** Old rule: any type with 2 live matches and no late
    observation in 2 days.
  - New, for events with neither: **start = expected expiration − the
    series' usual gap − 30 minutes**, from a fixed table of 35 series whose
    gap varied by 30 minutes or less (median 3 hours for most games, 4 for
    esports, 5 for broadcast-mention markets; `SERIES_START_OFFSET_HOURS`).
- Contracts per order: **5 → 2**; net contracts per market side: **5 → 2**.
  With $60 open (unchanged), about 2.5 times as many markets can be quoted
  at once.
- Milestone reads per pass: 30 → 60, because the longer window holds more
  events. The 45-second read budget is unchanged.
- Unchanged: $60 open, −$10 daily and −$40 total own loss stops, 20 orders
  per pass, 300 submissions a day (the most likely limit to bind; watched,
  not raised), 65-minute order lifetime, 8¢ minimum spread, the 64 series.

**Evidence** (simulated, in-sample, one contract, first in line): 10,223
pregame fills against v2's 1,152 on the same sampled markets; added fills
+8.50¢ a contract (t 12.92), +8.22¢ at flow share 0.25, positive in both
halves (9.40¢ / 5.21¢). Live, the $60 cap and 2-contract orders bound how
much of that appears.

**Version and checkpoint.** Orders carry `spread-maker-v3-24h-starts`. v3 is
judged on its own orders with the v2 bars: after 300 filled contracts or 4
weeks from its first order, continue if live profit per contract is above
zero, and stop and review if live fill share is below half the shadow's or
the −$40 stop is hit. v1 and v2 are reported apart. Resting v2 quotes are
managed like any other (kept or re-quoted) and stay measured under v2.

## 2026-10-23: Spread maker v3: changes after review (plan amendment)

*Written after an independent review of the v3 code and before any v3
order. The review found two ways v3 could quote into a live event and two
operational limits; the owner chose the answers to the limits.*

**Start times, tightened** (exploratory replay, simulated, in-sample;
`python -m research.spread_start_window final`, one more variant on the same
scan):
- *The earlier estimate wins.* An event's start is the earliest of a trusted
  milestone and the series estimate (before: the milestone won). On
  ticker-timed events, 26 of 2,666 trusted-type milestones were more than 20
  minutes late; 18 of those are in series with an estimate.
- *one_off_milestone is no longer trusted:* its late cases (8 of 381, all
  KXNCAABBGAME) are in a series without an estimate. Trusted types:
  baseball_game, basketball_game, cricket_match, hockey_tournament.
- *Series estimate = the larger of the median and the 99th-percentile gap
  between start and expected expiration, rounded up to 15 minutes,* minus
  30 minutes (before: the median). KXNBAPTSLEADER becomes 6 hours, KXRLGAME
  5.75 and KXNCAAWB spreads and totals 3.5; 31 series in all.
- *The earliest start ever seen for an event is kept* (`event_starts.json`),
  so an expiration that Kalshi moves later during a delay cannot move a
  start later.
- *Brent, S&P 500 and 10-year note dailies (KXBRENTD, KXINXDUD, KXTNOTED)
  are never quoted* (owner, 23 October): their "start" is a session open
  while the futures trade overnight, so pregame protects nothing.

Result of the tightened rule, 24→4 hours: 7,535 pregame fills (6.5× v2's
1,152), +8.92¢ a contract (t 11.83), halves 10.07¢ / 5.87¢, 6,451 fills at
flow share 0.25; the fills added over v2 earn +8.69¢ (t 10.74). Checked
against the 3,798 events whose ticker carries the real start, the estimate
(ignoring the ticker) would have cancelled quotes only after the real start
for 1 event (0.03%).

**Operations.**
- Submissions per New York day: 300 → **1,500** (owner, 23 October). Every
  quote is re-posted at least hourly; with about 30 markets quoted, 300
  would run out by early morning. Money limits are unchanged.
- Milestone reads go first to events without a series estimate, in a
  rotating order.
- The shadow ledger's trade and result reads are capped per pass and stop
  at a deadline, and the live measurements (fill share, markouts) now run
  before it.
- Standing checks record their rule version, and summaries count only the
  current version's. Measurements of v2 orders still pending when v3 starts
  are not completed (v2 is reported apart and not judged).

## 2026-10-23: Spread maker v3: changes after the second review (plan amendment)

*A second independent review of the v3 code, before any v3 order, found no
critical bug and two medium gaps. All changes below only ever move a start
earlier or quote less; none changes a money limit. Exploratory, one more
variant on the same scan (simulated, in-sample).*

- *Reads are no longer wasted.* Untimed events in series without an offset
  are read for milestones only in KXBIG3GAME, the one such series a trusted
  type ever dated in the scan (35 of 35 events); 4,422 of 11,263 events
  in the others (soccer, UFC, tennis, college football and similar) could
  never be dated and used up the 60 reads a pass. Read order, which the
  previous entry described wrongly: events with quotes resting, then four
  ticker-timed trust checks, then untimed events in offset series, then
  KXBIG3GAME, each group rotating.
- *Any milestone moves a dated start earlier.* An untimed event that has a
  trusted milestone or an offset takes the earliest of those and of any
  other milestone read for it, of any type (as ticker-timed events already
  did). A milestone of an untrusted type never dates an event by itself.
- *Live check of the offsets.* A ticker-timed event in an offset series
  whose expiry minus start exceeds the series gap plus 30 minutes (the
  estimate would come after the real start) suspends that series' offset
  for two days. In the scan this would have happened 3 times (KXMLBF3
  twice, KXRLGAME once).
- *The journal backs up the start memory.* A live pass also lowers each
  event's start to the earliest recorded with this bot's orders of the
  last two days, so a lost or unwritable `event_starts.json` cannot move
  a quoted event's start later. A failed cache write is reported.
- *A shadow-ledger failure* after a live pass still saves that pass's
  report and then fails the unit visibly.
- Known limit, unchanged: tickers whose team code starts with a digit (for
  example 100T) are read as untimed, which costs quotes, not safety.

Replay of the revised rule, 24→4 hours: 7,453 pregame fills (6.5× v2's
1,152), +8.96¢ a contract (t 11.79), halves 10.06¢ / 5.94¢, 6,363 fills at
flow share 0.25; added fills +8.73¢ (t 10.75). Estimates checked against
3,798 ticker starts: 1 would have cancelled after the real start.
