# NBA opening-night sizing review — October 19, 2026

**Decision:** Keep the **existing $50 cumulative submitted-cost NBA pilot**
for its first real-money opening-night session. Do not treat a $250 cash balance
as an authorization to risk $250. Increased sizing is **not empirically
justified** by the available one-season, fill-conditioned history. No live
trading code, environment, arm flags or risk limits were changed in this study.

Reproduction: `python -m research.nba_size_sensitivity`

[Actual CI sizing run](https://github.com/akilatrades/sports-market-maker/actions/runs/39259222191)
· [machine-readable results](../outputs/sizing/nba_oct2026_sensitivity.json)
· [NBA statistical launch audit](NBA_AND_MARKET_AUDIT_2026-10-18.md)
· [Tuesday go/no-go](TUESDAY_NBA_GO_NO_GO_2026-10-20.md)

## What was really tested?

Read the repository's 4,862 **hypothetical** 2025–26 NBA NO-maker
`outputs/bookline/fills_with_book.csv.gz` rows. Applied historical
book-advantage of 0–15¢, a 10–90¢ NO price, and >=2 independent
sportsbook quotes. **1,033 historically possible fills** remained
over **142 games**, all already timestamped in the same two-to-six-hour
pre-tip range as the live worker.

The new replay selects **the highest estimated book-advantage row per
game**, with deterministic tie-breaking, and processes games
chronologically. It submits at most **one hypothetical order per game**,
limits both contracts and reserved cost, **never recycles the lifetime
submission allowance**, and conservatively rounds a one-contract fee
up to a cent. It assumes a public trade-through can be captured at the
stated historical price, or reduces the count to 50%/25% of recorded
public print flow as a sensitivity. It does not remove losing outcomes
or increase order sizes after winners.

**These are still not actual fills**, and selecting from *already
possible-filled* historical rows is strong selection bias. It is
**not the launch worker's full backtest**, because we lack the
historical unfilled-order denominator, actual exchange queue, precise
one-hour expiry, live broker-side quote and injury verification, true
opening-night rotations and independent contemporaneous sportsbook
quotes. The historical book data may be observed after the historical
hypothetical order, which can introduce information leakage. Ordering
by book advantage is not a valid prospective trade list without
as-of timestamps.

## Starting $250 does NOT mean risking $250

Currently the actual production worker has:
**$50 lifetime allowance, $3 order/game/team, $15 active, $30/day,
5 contracts/order, one new order/five-minute scan, 10% reserved buffer**.
At the last verified signed preflight there was enough cash for the
$3 order cap, with no open inventory and NFL stopped. A **larger
cash balance with unchanged caps produces exactly the same orders**
in this historical replay.

Research-only alternative configurations changed **all relevant**
risk constraints consistently, not just the lifetime allowance:

| Scenario | Lifetime | Per order/game/team | Active | Daily | Contracts/order |
|---|---:|---:|---:|---:|---:|
| Current pilot | $50 | $3 | $15 | $30 | 5 |
| Same pilot, $250 cash | $50 | $3 | $15 | $30 | 5 |
| Hypothetical moderate | $75 | $4.50 | $22.50 | $45 | 8 |
| Hypothetical 5x | $250 | $15 | $75 | $150 | 25 |

Nothing in this table is deployed or newly authorized.

## New historical budget-limited replay

One possible fill order per independent game; historical outcomes
unchanged; reported results are illustrative and **not a future-return
forecast**.

| Scenario | Submitted reserve | Hypothetical contracts caught | Historical profit | Games selected |
|---|---:|---:|---:|---:|
| Current $50 | $49.86 | 99 | +$9.37 | 22 |
| $250 cash / same limits | $49.86 | 99 | +$9.37 | 22 |
| $75 moderate | $74.83 | 144 | +$12.54 | 21 |
| $250 and fivefold limits | $249.97 | 395 | +$28.43 | 22 |

Fivefold reserved submissions do **not** create fivefold profit
($28.43 vs $9.37), because the replay's selected order prices and
assumed accessible print flow differ across sizes.

**Capture sensitivity:** With only 25% of the *publicly observed*
trade-through flow hypothetically obtainable, the base scenario
had **+$6.00** and the fivefold-risk scenario **+$6.27**.
At 50% capture, those values were **+$9.71** and **+$14.44**.
These fractions are **arbitrary stress inputs**, not measured live
capture probabilities. Adverse selection could make returns worse
than random capture scaling predicts.

**Additional adverse price/fee drag:** Subtracting another 4¢
per hypothetical filled contract changes historical $50 profit to
**+$5.41** and fivefold case to **+$12.63** in these selected
games. This exercise does not cover a badly calibrated model,
correlated losses or poor future opening-night player roles.

## Conditional 800-game-bootstrap results (not calibrated risk forecasts)

Resampled the *selected historical game candidates* with replacement
using a deterministic seed, rerunning each budget from the start.
These are conditional on the outcome- and fill-selected dataset.

| Case | Bootstrap median $ | 5th–95th $ | Fraction negative |
|---|---:|---:|---:|
| $50 base | +7.72 | −10.24 to +24.58 | 25.4% |
| $75 moderate | +11.41 | −16.94 to +36.63 | 26.1% |
| $250 fivefold | +27.73 | −53.84 to +108.22 | 28.7% |

The strict two-book historical **per-contract** estimate in the more
comprehensive October 18 statistical audit was **+3.40¢**, with a
95% game-clustered confidence interval **−0.59¢ to +7.39¢**.
A broad in-sample growth figure is not evidence that this is a
stable opening-night income strategy. The historical strategy-only
regular-season replay had near-zero overall P&L and much higher
playoff returns; Tuesday is a new-season, high-role-uncertainty slate.

## What could a $250 account make Tuesday? Pure illustration

At an illustrative NO price **60¢** and the **unproven historical**
+3.40¢ after-fee edge, the buffer reduces allowable contracts
per independent game:

| Game/risk cap | Contracts/game | Max cost/game if all fill | Illustrative profit across 2 qualifying games | Across 3 qualifying games |
|---|---:|---:|---:|---:|
| $3/game, 5 cap | 4 | $2.40 | +$0.27 | +$0.41 |
| $4.50/game, 8 cap | 6 | $3.60 | +$0.41 | +$0.61 |
| $15/game, 25 cap | 22 | $13.20 | +$1.50 | +$2.24 |

If the two most recently sportsbook-covered games were the only
eligible games tomorrow, the **gross contract cost at risk** would
be approximately $4.80 (base), $7.20 (moderate) or $26.40
(fivefold). With three games, maximum fully filled principal
exposure rises to $7.20, $10.80 or $39.60 respectively. These
are arithmetic illustrations and assume **100% fill, the same
60¢ price, independent games and a true 3.40¢ edge**.
True edge can be negative, fees can change, and multiple prop
thresholds in the same game are not independent.

## Recommendation and evidence needed to scale

1. **Opening night:** keep the $50 lifetime and $3/game limits,
   passive-only orders, recent two-book quotes and a fresh signed
   GET-only preflight. Do not bypass alerts or force fills.
2. **After opening night:** reconcile exchange IDs, unique orders,
   maker/taker status, partial contracts, fees, queue movement,
   expired unfilled orders and final settlements. Report net
   dollars **per posted opportunity** and per independent game,
   not only profit per fill.
3. **Before any $75–$100 pilot:** confirm a useful number of
   real NBA fills over **multiple independent games**, no unexpected
   account/reconciliation failures, actual recent bookmaker matching,
   and explain how bigger quotes affect realized capture and adverse
   selection. Document a new version and explicit capital-at-risk
   approval.
4. **Reject the $250 full-risk scenario today.** Trading the
   entire account or raising all caps fivefold increases loss
   exposure without evidence that liquidity, fill quality or
   the true edge scales. You cannot extrapolate reliable
   monthly income from these results.

**Nothing in this research script calls the exchange, changes production
risk rules, or arms the NBA worker.**
