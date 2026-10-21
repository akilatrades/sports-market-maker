# Production account dashboard

The public dashboard at `/dashboard/` presents research, models and **only
exchange-verified NFL/NBA settled P&L** for portfolio visitors. The public P&L
comes from a sanitized, read-only settled-P&L feed on the server, polled every
15 seconds ([LIVE_ACCOUNT_PNL.md](LIVE_ACCOUNT_PNL.md)), with the committed
`outputs/dashboard/production_pnl.json` snapshot as a fallback. No independent
paper-ledger profits are displayed. The separate account view is served by the read-only service
on the existing trading Droplet at `http://127.0.0.1:8765`. Publishing the public
research page requires no terminal or SSH setup.
No balances, keys, raw journals or order IDs are uploaded to GitHub. The account
service binds to **127.0.0.1 only**, rejects foreign browser origins/hosts, and
allows only production GET requests. It cannot submit or cancel orders.

## Owner access

The account service is already installed on the server. To update its code
while both bots run, use `deploy/update_order_audit.sh` (see below); the older
one-sport `deploy/update_nfl_dashboard.sh` must not be used while NBA and NFL
share the account.

On your own computer, keep this terminal command running, using your existing
Droplet SSH login in place of `YOUR_SSH_LOGIN`:

```bash
ssh -N -L 8765:127.0.0.1:8765 YOUR_SSH_LOGIN
```

Then open <http://127.0.0.1:8765>. No API key belongs in the browser. Keep the same
local port (8765); the server checks Host headers to protect account data.

The service reads the existing `/etc/market-maker-prod-auto.env` through systemd.
It refreshes every 60 seconds, after each collection finishes. A snapshot older
than three minutes, or a failed refresh, is visibly stale. Old values retain
their original timestamp. Missing fields never become an invented zero balance.

If no snapshot loads:

```bash
systemctl status market-maker-dashboard.service --no-pager
journalctl -u market-maker-dashboard.service -n 20 --no-pager
```

Errors log exception classes only. Never paste credentials or the environment
file into chat. A stopped SSH tunnel disconnects the view; it does not stop the
account collector or change trading.

## NFL and NBA missed-order visibility (private)

The account page now has a **Kalshi / Exchange Order History** section with
one authenticated view of both NFL and NBA accepted orders. This reads
`GET /portfolio/orders`, `GET /portfolio/fills` and optionally recent
`GET /markets/trades` prints. The page distinguishes:

- **Resting, zero fills:** a live Kalshi order awaiting counterparties.
- **Confirmed zero-fill closure:** the exchange returns a closed order
  explicitly reporting zero filled contracts.
- **Partial / complete fills:** matched by exchange fill ID and quantity.
- **Unconfirmed:** order history has aged out, status is missing, or Kalshi
  fill totals do not reconcile. Unknown is never displayed as zero.
- **Potential opposing flow:** public YES-initiated contract volume through
  our price during a verified resting lifetime. This is *not* a proven
  missed fill: queue priority, cancel timing and other orders matter.

Market opportunities which the model declined **never became Kalshi orders**
and cannot appear in the exchange's order history. View the private
`last_scan.json` diagnostics separately for those candidates.

The new implementation changes only GET-based analysis and private rendering,
not the production worker's pricing, entry windows, order submission, risk
caps, or live P&L. Public GitHub Pages never receives order IDs or the
private audit. The private view continues to require a localhost SSH tunnel.

To deploy **this read-only reporting feature** while preserving the prior
state of both production timers, use the dedicated
`deploy/update_order_audit.sh` on the Droplet as root after GitHub CI
passes. It pauses both timers, waits for active scans, updates code, tests
the dashboard/audit, restarts the read-only account service and restores only
the timers that had been active. Do not use the older one-sport dashboard
updater while both pilots are running.

## What the numbers mean

- **Cash:** exchange-reported cash across the account.
- **Position value:** Kalshi's estimate of current open positions, not guaranteed
  proceeds from closing them. Total value is cash plus this estimate, not P/L.
- **Settled NFL and NBA P/L:** separate authenticated, owned strategy markets'
  settlement revenue minus entry costs and actual reported fees, across entry
  versions. Each cohort is matched through its own production order journal.
  A missing journal, absent fee/cost or unsettled order is shown as unavailable
  rather than $0. The private view refreshes both cohorts on account reads,
  independent of which market controls the execution/positions panel.
- **Filled orders / contracts:** one partially executed order can generate
  several fill records. Fills are deduplicated by exchange identity.
- **Submission allowance:** each bot's lifetime cap counts every attempted
  order's cost plus reserve, including canceled attempts. This is not cash spent
  or current open exposure. NFL: $50 lifetime, $3/order, $3/game, $3/team,
  $15 active, $30 daily, five contracts/order, two orders/game. NBA: $1,000
  lifetime, $4/order, $15/game, $10/team per day, $75 active, $75 daily, two
  contracts/order, ten orders/game. Shared: $1,050 lifetime, $105 daily, $90 active.
- **Last scan:** actual `last_scan.json` with named skips. A fresh account read
  does not imply the trader is active. A scan older than five minutes is flagged.

## New entry cohort

`nfl-no-v3-baseline-quote` (formerly `nfl-no-v2-reserved-edge`, identical except
that the optional second maker tick is now off) requires 3 cents of estimated
edge per contract **after the full existing 10% cost reserve, rounded up to cents**. This is a conservative
budget buffer, not a quote of the exchange's actual fee. It is deliberately not
calibrated to the single settled NFL game in the saved comparison. Probability
comes from the matched sportsbook line when available; otherwise from the model.

Projections must be at most 36 hours old, with no future timestamp. The original
projection timestamp, probability source, probability and buffered edge are
journaled per entry. Daily GitHub projection refreshes must still be pulled to
the Droplet; a healthy minute timer alone does not refresh model files. Stale data
blocks entries. Current resting orders are also withdrawn if model/availability
verification fails. Filled positions retain their original settlement exposure.

This remains a passive directional NO strategy holding to settlement. Improving
the price can improve execution but also reduce expected return, so the second
cent of improvement is off. An existing fill is not re-priced or liquidated.

## Public P&L policy

The recruiter-facing dashboard shows **no simulated ledger P&L, strategy-paper
equity curve or hypothetical profit scenarios**. Public NFL and NBA settled P&L
comes only from the sanitized, read-only server feed or the committed snapshot.
Neither contains an account balance, API credential, private order ID or
account journal. A value older than 90 seconds (feed) or 15 minutes (snapshot)
is labelled as a past result, never as current profit. The private dashboard
shows the full authenticated detail without exposing it through GitHub Pages.
