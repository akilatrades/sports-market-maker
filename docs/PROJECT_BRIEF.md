# Sports Market Maker — case study

**Python · prediction-market research · execution engineering · risk controls**

[Dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/) ·
[Source code](https://github.com/akilatrades/sports-market-maker) ·
[Research log](../RESEARCH_LOG.md) ·
[Design decisions](DESIGN_DECISIONS.md) ·
[Forward-test rules](FORWARD_VALIDATION.md) ·
[Deep audit matrix](DEEP_AUDIT_MATRIX.md)

## The question

Some traders on Kalshi, a US prediction-market exchange, pay predictably too
much. Can a small bot that only ever *rests* orders on the book (a maker)
earn from them **after fees and real exchange fills**, not just in a
backtest? Two places looked promising, so there are two strategies.

| | 1. Prop NO maker | 2. Spread maker |
|---|---|---|
| Markets | NBA and NFL player props ("25+ points?") | 64 series with wide spreads: esports, smaller leagues, cricket, soccer side markets and others |
| Who overpays | Fans buying YES on their player at the ask | Impatient traders who cross a spread of 8¢ or more |
| Order | One-sided: a NO bid one cent inside the spread | Two-sided: a YES bid and a NO bid, each one cent inside |
| How it earns | NO wins more often than its price implies | A filled YES+NO pair pays $1 for less than $1; a one-sided fill is held to settlement |
| Live since | 19–20 October 2026 | 22 October 2026 (pregame-only rules from 23 October) |

The prop strategy is **directional, one-sided liquidity provision**, not a
delta-neutral market maker. The spread maker is closer to classic market
making, but it holds inventory to settlement (with a cap) instead of
hedging, for the reason in [design decision 4](DESIGN_DECISIONS.md#4-hold-to-settlement-with-an-inventory-cap-instead-of-hedging).

## How I approached it

1. **Start with probabilities.** NBA player-stat models (expected minutes,
   shrunk per-minute rates, matchup, availability) and de-vigged sportsbook
   consensus, matched to Kalshi's exact game, player, stat and line.
2. **Test the trade, not the forecast.** Buying the model's side as a taker
   lost after costs, so I tested passive orders instead, then searched other
   Kalshi series for the same kind of mispriced flow.
3. **Say what the backtest assumes.** Historical fills are inferred from
   **public trade prints** and assume my order was first in line. Queue priority,
   adverse selection and some late-arriving inputs make every simulated
   figure optimistic, so replays also report a cautious 25%-of-flow case.
4. **Build bounded live infrastructure.** Signed Kalshi access, post-only
   orders, journal-before-send, reconciliation of every order, fill and
   position, per-bot and account-wide caps and loss stops, kill switches.
5. **Keep live and simulated results apart.** Exchange fills, fees and
   settlements are recorded separately from replays and never blended.

## Evidence, by tier

| Evidence | Tier | Observation | Important limit |
|---|---|---|---|
| Buying the model's side at the ask | Historical, pre-registered | Lost after spread and fees | Better forecasts did not make executable trades |
| Resting NO on 2025–26 NBA props | Simulated, **in-sample** | +1.65¢ per contract with no model (33,475 contracts, 1,013 games); +2.93¢ with a model veto | Rule chosen on this season; first-in-line fills |
| Smaller sportsbook comparisons | Simulated | About +3.4¢ to +4.0¢ per contract | Game-clustered intervals touch or cross zero |
| Two-sided quotes in 5¢+ spreads, all Kalshi | Simulated, in-sample | +2.44¢ per contract (76,694 fills, event-clustered t 15.9); positive in both halves (+3.07¢, +1.70¢); 67 of 369 series survive a 10% false-discovery correction | A wide-spread market's few prints decide its fills |
| Holding vs hedging those fills (8¢+) | Simulated, in-sample | Hold +3.91¢; sell back at market +0.22¢ | Exploratory, two extra variants |
| Signed NBA live audit, **21 Oct 2026 UTC** | Live | 9 accepted orders, 1 fully filled maker order, 1 reconciled **positive** settled market | Tiny; not a fill rate, proven edge or income |
| Spread maker, from 22 Oct 2026 | Live | Running (v2, pregame only, from 23 Oct); realized P&L on the [dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/) | Too early to mean anything |

About the one verified NBA fill: it filled within 15 minutes with positive
estimated edge, and the midpoint later moved its way,
**but the executable NO bid did not improve**, and it came from an older
rule version. Evidence:
[audit 1](https://github.com/akilatrades/sports-market-maker/actions/runs/39541489414),
[audit 2](https://github.com/akilatrades/sports-market-maker/actions/runs/39542054076),
[execution review](NBA_OVERNIGHT_AUDIT_2026-10-21.md).

## What did not work

Taking liquidity; gradient-boosted trees (better forecasts, no better
trades); recalibrating the model to Kalshi's lines (−22¢ per 100 orders); a
second cent of price improvement (−17¢ per 100); the same NO rule on game
winners; cancelling unfilled orders early (gave up 40–75% of the profit);
hedging one-sided spread fills; two-sided quotes in economics and financial
markets as a group (+0.27¢, no edge; three financial series still passed
the per-series check and are on the pilot list). Live, the spread maker's first timing rule
counted from Kalshi's expected expiration and on its first night quoted a
college football game after kickoff; since 23 October it quotes only
before a known start (simulated: quotes before the start made +9.9¢ a
contract, quotes during the game +2.7¢). Details in the
[research log](../RESEARCH_LOG.md) and the README's
[table](../README.md#what-did-not-work).

## What is being measured now

- **Fixed checkpoints, written before launch.** NBA v5 and v6 together
  (v6 trades 3 contracts an order from 23 October): 1,900 settled filled
  orders, the $5,000 allowance or 30 days, whichever comes first; positive with a
  game-clustered t of 2 or more counts as evidence of an edge, −1 or less
  means stop and review. At live fill rates 30 days likely brings 500 to
  1,100 fills (expected t about 1 to 1.5 for a 3¢ edge), so "keep
  collecting" is the likely first verdict. Spread maker (v2 judged on its own orders, from 23
  October): 300 filled contracts or 4 weeks; continue if live profit per contract is
  above zero; stop and review at its −$40 total stop or if live fills are
  less than half of what first-in-line fills would have been. That is a
  go/no-go check, not a significance test: 300 contracts in 5-contract
  orders cannot reliably tell 0¢ from 6¢.
- **The headline number: live fill share.** For every finished live order,
  the contracts that traded at or through its price while it rested,
  against the contracts it actually got. The first-in-line backtest assumes
  1.0; the report shows next to it what the cautious replay (25% of the
  flow) would have filled on the same orders. This decides whether the
  simulated edge survives, so it is computed after every live pass and
  reported in the private export.
- **One command grades both bots** against those bars from the private fills
  export: `python -m research.live_checkpoint --data <private export>`.
  Before a checkpoint it reports progress only ("no conclusion yet"),
  except that the spread maker's −$40 stop counts at any time. It prints,
  and writes nothing into this repository.

## Engineering decisions worth reviewing

| Concern | Where to inspect |
|---|---|
| Eight design decisions, with evidence and alternatives | [Design decisions](DESIGN_DECISIONS.md) |
| Model inputs and freshness | [NBA projections](../live/nba_projections.py), [input checks](../live/nba_inputs.py), [pregame context](../live/nba_pregame_context.py) |
| Posting, verifying and cancelling quotes | [NBA worker](../live/prod_nba_auto.py), [spread worker](../live/prod_spread_auto.py), [Kalshi client](../kalshi/trading.py) |
| Ownership, fills, fees, settlement, loss stops | [Shared account risk](../live/shared_account_risk.py), [tests](../tests/test_shared_account_risk.py), [spread tests](../tests/test_shared_account_spread.py) |
| Live grading against pre-written bars | [Live checkpoint](../research/live_checkpoint.py), [forward protocol](FORWARD_VALIDATION.md) |
| Hypotheses, negative results, limits on inference | [Research log](../RESEARCH_LOG.md), [NBA statistical audit](NBA_AND_MARKET_AUDIT_2026-10-18.md) |
| CI and owner-run deployments | [Tests](../.github/workflows/tests.yml), [deployment workflow](../.github/workflows/droplet-release.yml) |

## What is still unproven

- **Profitability.** No live sample yet is large enough to identify an
  edge; unfilled and still-resting orders count in the denominator.
- **Fill share and capacity.** Public prints are not fills. If the live
  share falls below what the cautious replay implies on the same orders,
  even the cautious replay overstates profit per day.
- **Selection.** Both strategies were chosen on 2025–26 data. The spread
  maker's 64 series were picked from the same scan they are judged on
  (+8.5¢ simulated in those series against +3.9¢ across all 8¢+ spreads,
  both first in line), so live results should be expected nearer the
  lower figure.
- **As-of inputs.** Some historical model inputs were not available hours
  before tip-off; live coverage of lineups and projected minutes is still
  being measured.

## What I would do next

- **Ladder pricing for the NBA lines v5 skips.** In a 7-game sample, 84%
  of Kalshi's lines (rungs) had no two-book sportsbook line, and a ladder
  fitted to the books' other lines could price 79%. On those lines it made
  +4.6¢ against +2.3¢ for the current rule (simulated, not yet
  significant). A paper test comes first.
- **Shorter spread orders,** so the spread maker can quote closer to the
  start without resting into it, tested on minute-level prints before any
  change.
- **Size only after the checkpoints,** never before.

**What I take from it:** the hard part was not predicting NBA statistics.
It was connecting pricing uncertainty to market microstructure, live API
execution and operational controls, and keeping an honest loop from
simulated fills to exchange-confirmed results, including the night the
live market showed me a rule I had to change.

*Research and software development used AI assistance; the repository
keeps the tests, experiment logs and evidence sources for review.*
