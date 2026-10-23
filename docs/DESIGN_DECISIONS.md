# Design decisions I would defend

Eight choices that shape what this project's numbers mean. Each has the
decision, why, the evidence (with its tier: simulated, in-sample or live),
the alternative and what it would have cost, and where it lives in the code.
The one-sentence version under each heading is the short answer.

---

## 1. Judge results by game (or event), not by fill

*Props in the same game move together, so a game is closer to one
observation than each fill is.*

- **Why.** If a player's minutes collapse, his points, rebounds and assists
  overs all fail together, and so do his teammates' lines. Treating 40 fills
  in one game as 40 independent coin flips overstates confidence.
- **How.** Profit per contract is a weighted mean; its standard error adds
  up each game's residuals first and then squares them
  (`clustered_mean_t` in `research/fill_sizing_replay.py` and
  `kalshi/stats.py`). Spread-maker results are clustered by Kalshi event
  (`research/strategy_sweep.py`, `research/live_checkpoint.py`).
- **What it changes.** One contract's result has a standard deviation of
  about 44¢. A 3¢ edge would need about 900 fills for t ≈ 2 if fills were
  independent, and about 1,900 once same-game correlation is counted
  (2025–26 replay). That is why the NBA checkpoint is 1,900 settled fills,
  not a few hundred.
- **The alternative.** Per-fill t-statistics. On the 20,641 model-veto
  fills of 2025–26 the headline t is 9.7 if fills are treated as
  independent and 6.1 clustered by game; for the v5 rule's orders the
  variance is about 2.2 times the independent figure (design effect 2.18).
  Enough to call a lucky month significant.

## 2. Treat backtest fills as optimistic, and measure the real share

*A public trade at my price only means I could have filled if I was first
in line; usually I am not.*

- **Why.** Historical fills come from public trade prints. Other orders
  already resting at the same price get filled first, and the trades that
  reach a resting order can be the ones that move against it (adverse
  selection). In the NBA replay the fills were in fact favourable (filled
  orders beat unfilled ones by +2.0¢, t 3.0), but the replay has no queue,
  so it cannot show what happens behind other orders.
- **How.** Replays report the first-in-line case and a cautious case in
  which each contract that trades at my price reaches my order with probability
  0.25 (`flow_share` in `research/fill_sizing_replay.py`). Live, the spread
  maker now measures it directly: for every finished order it counts the
  contracts that traded at or through its price while it rested, and
  compares them with what it actually filled (`score_live_windows` and
  `fill_share` in `live/prod_spread_auto.py`). NBA has a similar measure,
  "volume-weighted capture" ([forward protocol](FORWARD_VALIDATION.md)).
- **What it changes.** A live share of 1.0 would mean the first-in-line
  backtest was right. The cautious replay does not mean a share of 0.25:
  when many contracts trade through, a 25% share still fills most of a
  5-contract order. So the bot reports what the cautious replay would have
  filled on the same orders next to the live share. Below that benchmark,
  even the cautious replay overstates fills; fewer fills mean
  proportionally less profit per day, and the fills I do get may be the
  worse ones (adverse selection). This is the most decision-relevant live
  number in the project.
- **The alternative.** Assuming every print is a fill: the classic way a
  market-making backtest looks great and trades badly.

## 3. Post-only, one cent inside: never pay the spread

*The first idea was buying the model's side at the ask; the spread and
fees ate it.*

- **Evidence.** A pre-registered test of buying the model's preferred side
  as a taker lost money after spread and fees. Resting NO orders made
  +1.65¢ per contract with no model and +2.93¢ when the model only vetoed
  unfavourable lines; resting YES lost 2.0¢ (2025–26 NBA, simulated,
  in-sample; [research log](../RESEARCH_LOG.md)).
- **How.** Every order is post-only (rejected rather than allowed to take
  liquidity). The prop maker quotes NO one cent better than the best bid;
  the spread maker quotes both sides one cent inside 8¢+ spreads, priced
  from the order book with its own orders removed so it never bids against
  itself.
- **The alternative.** Taking liquidity: faster fills, but the cost is the
  whole spread plus fees on every trade.

## 4. Hold to settlement, with an inventory cap, instead of hedging

*Selling a one-sided fill back pays the very spread the strategy earns.*

- **Evidence (spread maker, 8¢+ spreads, simulated, in-sample).** Holding
  every fill: +3.91¢ per contract (profit factor 1.33). Selling one-sided
  fills back at the market an hour later: +0.22¢ (profit factor 1.03), with a
  worse worst day. One-sided fills averaged +5.0¢ held and −4.6¢ sold.
  Holding with a per-market inventory cap: +3.60¢, about the same profit per
  unit of risk as holding everything, with 29% less daily volatility.
- **How.** At most 5 contracts held or resting on one side of a market;
  orders shrink to fit (`MAX_NET_PER_MARKET` in `live/spread_policy.py`;
  `desired_quotes` in `live/prod_spread_auto.py`).
- **The alternative.** Hedging feels safer but turns a +3.9¢ strategy into
  roughly break-even.

## 5. Control false discoveries when searching many markets

*Test 369 series and some will look great by luck.*

- **Evidence.** In the strategy sweep, 369 series had enough data; 72
  showed t ≥ 2 and only 10 showed t ≤ −2. A Benjamini–Hochberg correction at
  a 10% false-discovery rate kept 67. Two-sided quoting in 5¢+ spreads was
  positive in both halves of the sample (+3.07¢ and +1.70¢), and the top 10
  series supplied only 15% of the profit, so it is not one lucky market.
- **What it does not fix.** The 64 series the spread maker trades were
  chosen on the same data, so their simulated edge (+8.5¢ at 8¢+ spreads,
  first in line) is biased upward; across all 8¢+ spreads it was +3.9¢.
  Expect live results nearer the lower number. Every confirmatory test
  is written into the research log before it runs, and every variant tried
  is counted.
- **The alternative.** Picking the best-looking series from a scan and
  calling it an edge.

## 6. Stop on anything unexplained

*A trading bot that guesses is more dangerous than one that stops.*

- **How.** Every order and cancel is written to a journal before it is
  sent. Each pass reconciles the exchange's orders, positions and fills
  against all three bots' journals; anything unowned, or any order whose
  outcome cannot be proven, halts every bot until the owner reconciles it
  (`live/shared_account_risk.py`). One shared daily and total loss stop
  covers all bots, on top of each bot's own limits.
- **What it caught.** Independent code reviews before launch found, among
  others, that the spread maker would have chased its own quotes a cent at a
  time; that its loss stops could not see YES+NO pairs, which Kalshi nets
  before settlement (now counted from its own fills); and that a partial
  fill just before a cancel could have broken the inventory cap. The first
  release then stopped itself when Kalshi rate-limited balance reads,
  rather than trading on a check it could not finish. Each was fixed with a
  test.
- **The alternative.** Retrying and carrying on: fine until the one time an
  order exists that the bot does not know about.

## 7. Write the test down before running it

*Results only mean something if the bar was set first.*

- **How.** Confirmatory tests get a research-log entry with the question,
  method and pass/fail bar before they run; everything else is labelled
  exploratory, and the number of variants is reported. Live checkpoints are
  fixed in advance (NBA v5: 1,900 settled fills, the $2,000 allowance or 30
  days; spread maker: 300 filled contracts or 4 weeks).
  `python -m research.live_checkpoint --data <private export>` grades each
  bot against its own pre-written verdict rules.
- **The alternative.** Choosing the evaluation after seeing the data, which
  turns almost any strategy into a success story.

## 8. Quote only before the event starts

*A resting order in a live game is filled mostly when the game has just
moved against it.*

- **What happened.** The spread maker's first rule quoted markets 4–7
  hours before Kalshi's expected expiration. For college football that
  time is 6 hours after kickoff, so on its first live night (22 October)
  it quoted a game 33 minutes after kickoff, and esports orders posted
  minutes before a match rested into it.
- **Evidence (simulated, in-sample, first in line).** In series whose
  event ticker carries the start, quotes resting wholly before the start
  made +9.9¢ per contract (t 9.9); quotes resting during the game made
  +2.7¢ (t 2.3). Across all 64 series, the last hour before the cutoff,
  when events often start, made +6.4¢ against +9¢ to +12¢ earlier.
- **How.** v2 needs a known start, from the event ticker or from Kalshi's
  milestones (trusted by milestone type, and only after they have matched
  ticker times and never been late). A new quote needs the start at least
  85 minutes away, each order's 65-minute exchange expiry is capped at 20
  minutes before the start, and every resting quote is cancelled then
  (`live/prod_spread_auto.py`: `ticker_start`, `prefetch_starts`,
  `order_start`).
- **The cost.** With ticker times alone, v2 keeps about a sixth of v1's
  simulated profit, at a higher +10.5¢ per contract. Most of what it drops
  came from the hours that paid least and that the backtest models worst.
- **The alternative.** Quoting through the game, which would need a bot
  that reacts in seconds rather than every 10 minutes, and even in the
  backtest barely paid.
