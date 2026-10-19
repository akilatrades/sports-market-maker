# Live funded Kalshi P&L on the public dashboard (30-second account polling)

**Purpose.** Display automatic realized **settlement** gains and losses from
the actual FUNDED Kalshi account—not a static GitHub snapshot. The public
dashboard displays three metrics:

- **FUNDED ACCOUNT:** net results from *all available account settlements*,
  including manual orders and both NFL/NBA bots.
- **NFL:** settlement results *owned by the NFL production journal*.
- **NBA:** settlement results *owned by the NBA production journal*.

Real money only. No paper, demo, projections or historical simulation.

**Accounting boundary:** This is settlement-realized P&L, *not* an all-time
tax statement or the entire set of realized exits. Early sales/cash-outs,
rebates/credits and settlements already archived by Kalshi may not appear.
We will need an additional historical-positions / fills reconciliation
before describing it as complete account lifetime P&L. Cash balance is
NOT P&L because deposits and open-position purchases change cash.

## Actual update behavior

`live.public_pnl_feed` polls signed production Kalshi settlements and
bot-owned fills about every **30 seconds**. It runs on the owner's
DigitalOcean Droplet under `trader`, using the existing production
EnvironmentFile and `ReadOnlyClient` (GET-only). The public GitHub Pages
site checks a **sanitized HTTPS URL every 15 seconds**.

**Expected displayed lag:** usually within 30–45 seconds *after Kalshi
publishes a settlement*. The exchange may take longer to settle a market.
This is near-real-time account reporting, not a synchronous settlement
webhook. It never pushes new commits per settlement.

On source error or stale snapshots (more than 90 seconds old), the
public *current* amount disappears instead of falsely staying green.
The old committed report is used only if no live endpoint has been
configured; it is labelled historical when stale.

## Security boundary

The private signed Kalshi API client **NEVER runs in the browser**.
The local feed only returns two cohort aggregates, one settlement
account aggregate, source timestamps and status. It never returns
balances, deposits, account IDs, player names, order IDs, tickers,
fill details, private journal data or keys.

- Internal server listens only at **127.0.0.1:8766**.
- Its HTTPS proxy must publish **only `GET /v1/pnl`**; never reverse-proxy
  **127.0.0.1:8765**, which is the private account dashboard.
- Browser requests are allowed only from
  `https://akilatrades.github.io` (CORS). CORS is not authentication:
  **the aggregate P&L becomes publicly visible** to anyone who visits
  its URL. This is what a recruiter-facing dashboard requires.
- Do not put a Kalshi private key, a GitHub token, a Droplet admin API,
  or a secret in `dashboard/live-pnl-source.json`.
- No trades are placed, canceled or changed by the new service.

## Phase A: owner validation on DigitalOcean (read-only, no public exposure)

Run only when it is safe to update the code checkout and no active
trader is importing modules while Git is updating:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader git pull --ff-only origin main
sudo systemd-run --wait --pipe --collect \
  --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile=/etc/market-maker-prod-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m live.public_pnl_feed --once
```

This command displays sanitized JSON for owner review and does **not**
launch a service, change orders or publish anything. Confirm that the
FUNDED ACCOUNT and NFL settlement totals both match the previously
signed **−$0.69** when no additional manual trades occurred. If
they differ, inspect the source privately. **Do not** activate the
public endpoint until reconciliation succeeds.

## Phase B: private localhost feed, still not publicly exposed

After Phase A succeeds:

```bash
sudo cp deploy/market-maker-live-pnl.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now market-maker-live-pnl.service
sudo systemctl status market-maker-live-pnl.service --no-pager
curl -fsS http://127.0.0.1:8766/v1/pnl
```

This only enables the **read-only reporting service**; it does not
start NBA or NFL trading. It does not expose port 8766 externally.
The printed response must contain **only** redacted aggregates.

## Free HTTPS hostname (no signup)

If you do **not** own a domain, use
[FREE_PNL_HTTPS_SSLIP.md](FREE_PNL_HTTPS_SSLIP.md):
free `sslip.io` DNS maps your Droplet public IP to a hostname, and
Caddy provides a free auto-renewed HTTPS certificate. Start with the
**read-only** `deploy/free_pnl_https_check.sh` before touching ports or
services. Once the signed amounts and external HTTPS URL are verified,
configure the same `dashboard/live-pnl-source.json` below.

## Phase C: HTTPS with your domain

GitHub Pages uses HTTPS, so a plain HTTP Droplet URL will be blocked
as mixed content. Set up a stable hostname (e.g.
`pnl.your-domain.example`) with an A record pointing to the Droplet.

An HTTPS reverse proxy such as Caddy can use this **example** Caddyfile,
after you substitute your **real hostname** and install/configure
Caddy according to your OS:

```caddyfile
pnl.your-domain.example {
    @pnl path /v1/pnl
    handle @pnl {
        reverse_proxy 127.0.0.1:8766
    }
    handle {
        respond 404
    }
}
```

Caddy must obtain a valid certificate and accept internet traffic
on standard ports 80/443. Keep port 8766 closed in both the OS and
DigitalOcean firewalls, and **never expose port 8765**. If a
reverse proxy is already installed on port 443, merge the site into
its existing configuration instead of attempting to run two competing
servers. Verify HTTPS and the CORS response before modifying GitHub.

## Phase D: point the static website to the live source

Only after Phase C works, edit the **public, non-secret** config:

```json
{
  "api_url": "https://pnl.your-domain.example/v1/pnl"
}
```

The file is `dashboard/live-pnl-source.json`. Commit this file once.
The existing site will then poll it every **15 seconds**, displaying
FUNDED ACCOUNT + NFL + NBA numbers from your signed Droplet read-only
collector, with visible as-of timestamps. No per-settlement GitHub
commits or publishing token are necessary.

To disable public live reporting, clear `api_url` in that JSON and
disable the local feed service. It returns to timestamped committed
snapshots. The private account dashboard remains on its own
localhost port and is unaffected.

## Before claiming 'all funded-account realized P&L'

Kalshi's REST API distinguishes live settled, archived historical
positions and exits before settlement. The initial secure live feed
sums exchange-verified `GET /portfolio/settlements` results and
therefore captures newly settled NO/YES wins and losses, including
manual markets. It **cannot yet guarantee every closed-position sale,
archive-period settlement or credit** is in the total.

The exchange also exposes `GET /portfolio/positions?settlement_status=all`
and `GET /historical/positions`, including
`realized_pnl_dollars`; these require a separate, deduplicated
accounting and fee-basis validation before integration. Do NOT simply
add these figures on top of settlement P&L or double-count markets.
In the meantime, the public card is explicitly labelled
**'settled P&L'**, and the raw account cash balance is never
presented as profit.

## Rollback / safety

```bash
sudo systemctl disable --now market-maker-live-pnl.service
```

Also remove/revert the public HTTPS proxy and empty `api_url` if
desired. Neither action changes existing orders, trading timers,
kill switches or the private P&L view.
