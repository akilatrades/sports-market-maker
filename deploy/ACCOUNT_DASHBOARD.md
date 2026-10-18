# Production account dashboard

The public dashboard at `/dashboard/` presents research, models and results for
portfolio visitors. The separate account view is served by the read-only service
on the existing trading Droplet at `http://127.0.0.1:8765`. Publishing the public
research page requires no terminal or SSH setup.
No balances, keys, raw journals or order IDs are uploaded to GitHub. The account
service binds to **127.0.0.1 only**, rejects foreign browser origins/hosts, and
allows only production GET requests. It cannot submit or cancel orders.

## Owner deployment

After this change is merged, run on the Droplet as root:

```bash
curl -fsS https://raw.githubusercontent.com/akilatrades/sports-market-maker/main/deploy/update_nfl_dashboard.sh -o /tmp/update_nfl_dashboard.sh
bash /tmp/update_nfl_dashboard.sh
```

The update script pauses the NFL timer, waits for an in-flight worker to finish,
pulls main with `--ff-only`, installs/restarts the read-only account service, and
restores the timer only if it was already active. It preserves the private
journal, KILL switch, credentials and all dollar limits. It does not enable an
inactive trader or run a demo. A failed pull stops the update; resolve the Git
problem without resetting the production journal.

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

## What the numbers mean

- **Cash:** exchange-reported cash across the account.
- **Position value:** Kalshi's estimate of current open positions, not guaranteed
  proceeds from closing them. Total value is cash plus this estimate, not P/L.
- **Settled NFL P/L:** owned strategy markets' settlement revenue minus entry
  costs and actual reported fees, across entry versions. An absent fee/cost makes
  the result unknown. With no settlements, display “No settled NFL markets yet.”
- **Filled orders / contracts:** one partially executed order can generate
  several fill records. Fills are deduplicated by exchange identity.
- **Submission allowance:** the existing lifetime $50 cap counts every attempted
  order's cost plus reserve, including canceled attempts. This is not cash spent
  or current open exposure. Other caps remain $3/order, $3/game, $3/team,
  $15 active, $30 daily, five contracts/order, two attempted orders/game.
- **Last scan:** actual `last_scan.json` with named skips. A fresh account read
  does not imply the trader is active. A scan older than five minutes is flagged.

## New entry cohort

`nfl-no-v2-reserved-edge` requires 3 cents of estimated edge per contract **after
the full existing 10% cost reserve, rounded up to cents**. This is a conservative
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
the price can improve execution but also reduce expected return. The optional
second tick falls back to the baseline maker quote when it would consume the
new minimum edge. An existing fill is not re-priced or liquidated by this update.
