# Spread v4: completion pilot candidate

Status: implementation candidate, live activation disabled. This change repairs
how the second leg is managed; it does not establish a profitable strategy.
Version: `spread-v4-completion-pilot-1`. Do not tune this version in place.

## Behavior

V3's closing quotes depended on the same wide-spread and expiry filters used
for new entries. V4 manages held inventory before scanning for opportunities.
It prices a closing leg from actual FIFO fills and their allocated fees. It
never deliberately adds to a held position, and closes no more than is held.

1. Read signed account data; reconcile ownership, fees, quantities and P&L.
2. If inventory exists, block every new entry. Take an available net profit
   with a limit IOC that the exchange enforces as reduce-only; otherwise post
   only the opposite side at a price above the profit floor.
3. At 60 minutes from the oldest unmatched fill, or 20 minutes before the
   earliest known event start, attempt a bounded-loss IOC. If the price is too
   poor or liquidity is absent, retain the unmatched position, block entries
   and report the obstruction. No order after the event starts.
4. When flat, quote at most one market across the whole pilot. Require two-sided
   depth, current fee metadata, a small estimated immediate liquidation gap,
   and a known pregame start. Never reuse an event that has a fill, or an event
   already touched by a legacy strategy. One new order per pass means the
   second initial quote waits for another account read.

The two entry legs are not atomic. There can be one-sided exposure before the
next pass, and passive orders can fill while cancellation is in flight. Every
cancel ends the pass: replacement requires a new account read. Passive closes
cannot use Kalshi's reduce-only flag, which is limited to IOC orders. Their
quantity is locally capped after that reconciliation barrier.

## Fixed pilot settings

These are conservative starting controls, not optimized backtest results.

| Setting | Candidate | Existing v3 maximum |
|---|---:|---:|
| Initial order / net inventory | 1 contract | 5 contracts |
| Concurrent market/event groups | 1 | Multiple |
| Cash cost cap, including fee reserve | $10 | $120 |
| Pilot realized loss stop, daily / total | $1 / $3 | $15 / $40 |
| Net profit target | 2c per contract | No cost-based completion target |
| Timeout loss allowance | 10c per contract | Held to settlement |
| Resting order expiry | 90 seconds | 65 minutes |
| Timer interval | 30 seconds after each pass | 10 minutes |

The original all-version spread and account-wide loss stops still apply.
The original 1,500 daily submission cap also includes the new pilot. A loss
stop cancels resting orders and blocks further submissions, including exits.
The $1 realized stop is not a maximum possible loss: open positions, slippage,
gaps, outages and a blocked exit can leave additional losses up to the stake.
The timeout price bound is not a guaranteed stop loss.

Entry still uses the existing series allowlist and 4–24-hour expiry window,
but only ticker-timed events qualify; no inferred expiry offsets. Earliest
recorded/ticker/milestone time wins. Depth must be at least 10 contracts at
each external best bid, quoted spread at least 8c, and estimated immediate
liquidation cost no more than 5c/contract including conservative fee reserves.
There must also be 2c/contract left if both proposed entry legs fill.
These filters measure executable conditions; they do not predict future fills.

Only binary $1 contracts with known quadratic fees are supported; combos and
unknown fee schedules fail closed. The fee reserve uses the worst value of
`p(1-p)` plus 1c/contract to cover $0.0001 rounding on every 0.01-contract
fragment. Price improvement on a closing IOC is accounted at the actual fill
price. Missing fees, excessive observed fees, an unowned fill, missing signed
history or inconsistent positions halt the worker. No fee rebates are assumed.

## Release and study isolation

Do not use the existing funded code deployment workflow for this release.
The `Stage spread v4 candidate (no live activation)` workflow, after merge and
CI, copies an immutable revision to `/home/trader/spread-v4/releases/<sha>`.
It runs a signed-read preview and writes a private `candidate.json` receipt.
It does not install/enable a timer, change environment files, create an arm
gate, remove any kill file, restart a worker, or place/cancel an order.

The existing v3 production checkout remains at
`fe7a5e7a8cfff8eeb5018d5d047f549f8a7f7cbd`. Its policy, recorder and fixed
October 25–November 24 enrollment window (December 1 settlement follow-up)
remain unchanged. V4 uses a distinct strategy version and excludes legacy
events. Its ownership records use the existing spread journal, so the frozen
observer must continue filtering strictly by v3 strategy identity.

Before a funded pilot can be approved:

- Review the exact CI-passing revision and this specification. Confirm the
  signed-read preview reconciles. This candidate restores the approved manual
  close accounting already deployed in `fe7a5e7`, which was absent from the
  current main snapshot. Only existing, hashed, explicitly approved reducing
  fills are recognized. It creates no new approvals and changes no journal.
- Exercise the release in the exchange demo environment, including a partial
  close, IOC price improvement, an expired order and lost-response recovery.
  Preview is not a fill simulator, and unit tests do not validate exchange behavior.
- Review prospectively recorded quotes and liquidity. Earlier v3 checkpoint
  opportunities are hindsight diagnostics, not a v4 backtest. Report paired
  and unmatched outcomes together, after fees, by independent event; do not
  promote from completion rate or a few winning trades alone.
- Keep NBA/NFL funded workers paused, with their funded timers disabled and
  services inactive. They must not run an older ledger that
  assumes every v4 IOC filled at its limit. Paper research is independent.
- Keep legacy KILL markers; disable the old spread timer and ensure its
  service is inactive so it cannot cancel v4 quotes. Do not change the frozen
  production checkout. Install the supplied v4 units separately and point
  `/home/trader/spread-v4/approved` at the reviewed release.
- A separate live approval creates root-owned, non-group-writable
  `/etc/market-maker-spread-v4.json`, containing `version`, `source_sha256`
  (from `python -m live.prod_spread_v4 --digest`), `approved_at`, and
  `expires_at` no more than 24 hours later. It also explicitly sets
  `SPREAD_V4_ARM=YES` in `/etc/market-maker-spread-v4.env`. Staging cannot do this.

There is no automatic promotion or size increase. Gate expiry prevents new
submissions; outstanding passive quotes expire within 90 seconds. For an
authorized stop, `V4_KILL` in the spread state directory triggers owned-order
cancellation on the next armed pass. If the gate has expired, use a separately
authorized cancellation action or allow exchange expiry; changing the gate is
not required just to make quotes expire.

Unknown POST outcomes are journaled and never retried. Resolve them using the
existing signed-read reconciliation command from the isolated release; do not
delete an intent or assume a timeout means rejection.

Detailed proposals, fee metadata and external books stay in private state.
`v4_last_scan.json` exposes recording/execution failures separately from P&L.
Public logs contain only counts and decision/error categories.

## API references checked October 30, 2026

- [Create Order V2](https://docs.kalshi.com/api-reference/orders/create-order-v2):
  reduce-only requires IOC; IOC cannot carry an expiry or be post-only.
- [Fee schedule, effective July 7, 2026](https://kalshi.com/docs/kalshi-fee-schedule.pdf):
  quadratic maker/taker fees and centicent rounding.
- [Series metadata](https://docs.kalshi.com/api-reference/market/get-series) and
  [market metadata](https://docs.kalshi.com/api-reference/market/get-market).
