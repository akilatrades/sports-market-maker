# NBA forward validation: 30-day private evidence study

**Start:** the first exchange-accepted live NBA order, observed October 20,
2026. The start time comes from the append-only production journal, not the
README or a manual clock, and the private account panel counts the 30 days
from it, across rule versions. Under
[FORWARD_VALIDATION.md](FORWARD_VALIDATION.md) each rule version is also
judged as its own group, so the current rules
(`nba-no-v4-smaller-orders-edge3-baseline`) get their own 30 days from their
first accepted order.

**Purpose:** determine whether the historically simulated NBA NO-bookline return
survives real maker queue priority, current player roles, actual fees and settlement.

## Live policy

- NBA: post-only passive NO orders, started 2–6 hours before verified tip
  and resting until tip.
- Current limits are listed in
  [PROD_NBA_AUTO.md](../deploy/PROD_NBA_AUTO.md#execution-policy) and come
  from `live/prod_nba_auto.py`. The lifetime allowance counts even
  exchange-rejected attempts and does **not reset automatically**.
- The shared-account limits, account-wide loss stops and kill switch still
  apply independently.
- No auto increase to per-game size, no retry of rejected tickers,
  no changes to maker quote prices or entry filters.
- Nothing here authorizes recurring deposits, extra budget, timer starts,
  automatic order placement or account transfers.

## Daily observations and reconciliation

The **private** `/api/account` snapshot now contains `nba_validation`,
derived exclusively from production journal events and authenticated
Kalshi order/fill and settlement reads. It powers the private Trading Desk
**30-day live evidence** panel. It reports:

- accepted vs. attempted orders and unspent lifetime submission allowance;
- independent NBA games with accepted orders and with real fills;
- orders currently waiting, confirmed no-fill closures, partial/full fills;
- fill rate only for *closed orders with known outcomes*;
- maker share only when all relevant executed contracts have verified flags;
- realized net NBA settlement P&L only after verified cost, fill and ownership
  reconciliation; open marks and order entry costs are not realized loss;
- 30-day review date and missing/unknown exchange history explicitly.

None of this account data is published to GitHub Pages. A snapshot may be stale,
and the data must not be copied to a public recruiter-facing dashboard.

## Research validity

Review the frozen entry policy by **independent game**, not by counting
nested thresholds for the same player as independent trades. A nominal
three-cents-per-contract modeled edge, successful POST, initial fill, or a
profitable individual night **is not evidence of durable profitability**.

Measure cumulative *verified* settlement P&L alongside total accepted-order
and eligible-candidate denominators; include exchange-confirmed no fills and
unfilled orders that consume submission budget. Inspect quote-time estimated
edge, fees, 5/15/60-minute markouts, queue movement, maker share and price
changes. Do not infer missing maker flags or public prints as fills.

The project has a 30-day review checkpoint, and its forward-validation
protocol targets hundreds of settled fills before strong inference. At the
current small limits, 30 days may not reach that target.
**Time passing is not a statistical significance test.** If the account
reaches its lifetime allowance sooner, stop new submissions automatically as
the current worker already does; evaluate existing orders without rewriting
history. Explicitly approve any later funded pilot with new limits and tests.
Do not delete journals or remove safety files to get more trades.

## Stop/review triggers

Stop **new** live entries and investigate any unresolved signed-exchange
order ID, unknown fill or missing position, wrong market/shard, foreign account
inventory, incorrect fee fields or model-data freshness failure. Also pause
if observed live fill selection appears consistently adverse to our quote
edges; a small negative sample isn't proof of no edge, but capital is finite.

The next budget decision requires reconciliation and multiple independent
settled NBA games; record the reason for any strategy revision and start a
separate version/cohort before evaluating its out-of-sample returns.

This change only adds private **read-only** reporting; it does not modify
production order sizing, live runtime, account balances, or timer state.
