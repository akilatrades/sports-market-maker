# Free HTTPS for the funded Kalshi P&L dashboard — sslip.io + Caddy

No paid domain name, DNS account, hosting plan or certificate purchase
needed. This uses the existing **DigitalOcean Droplet** (whose current
cost remains unchanged), **free [sslip.io DNS](https://nip.io/)** and
free Caddy-managed public TLS certificates.

**CAUTION:** This makes **aggregate funded-account settlement gains/losses
public**. Only continue if you approve that visibility. It does NOT
publicize balances, order IDs, player names, cash deposits or credentials.
The private account view remains on **127.0.0.1:8765**.

## Step 1 — read-only host check, no changes

In the DigitalOcean web terminal:

```bash
cd /home/trader/sports-market-maker-prod-auto
curl -fsSL https://raw.githubusercontent.com/akilatrades/sports-market-maker/main/deploy/free_pnl_https_check.sh \
  -o /tmp/free_pnl_https_check.sh
bash /tmp/free_pnl_https_check.sh
```

This generates your free hostname automatically:
`<your-public-IPv4-with-dashes>.sslip.io`, resolves it to the
Droplet, checks whether **80/443 are already occupied**, and reports
the trade timer states. Nothing is installed, stopped, activated or
exposed. **Bring this output back before proceeding** if there is an
existing web server, DNS lookup fails, or you're uncertain.

sslip.io names use your public IP; if the IP changes, the hostname
changes. This free third-party DNS service is convenient but carries
dependency/availability and certificate rate-limit risks.

## Step 2 — read-only signed trading-account reconciliation first

When **no active trade worker is running**, update the checkout.
Do not pull during in-flight real-money execution or change a live
trade timer just for reporting. Keep NFL/NBA activation separate.

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

**STOP if the amounts don't reconcile.** FUNDED ACCOUNT includes all
API-visible account settlements (including manual trades). NFL/NBA are
strictly journal-owned settled results. They need not equal one another.
This does not yet capture early-sales, historical archived results or
account credits, so do not label it complete lifetime realized P&L.

## Step 3 — start localhost-only GET read service

Only if Step 2 passes:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo install -m 644 deploy/market-maker-live-pnl.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now market-maker-live-pnl.service
sudo systemctl status market-maker-live-pnl.service --no-pager
curl -fsS http://127.0.0.1:8766/v1/pnl
```

The service performs authenticated Kalshi GET reads every **30 seconds**.
The local port **8766** must NEVER be opened externally; nor should
private dashboard port **8765**.

## Step 4 — put HTTPS in front

**FIRST verify port 80 and 443 are unoccupied.** If your host already
runs Caddy/Nginx/Apache, integrate into that *existing* server instead
of installing another one.

If nothing owns 80/443, the standard Ubuntu package is a simple path:

```bash
sudo apt-get update
sudo apt-get install -y caddy
```

Use the same public IPv4 generated in Step 1. In a terminal shell:

```bash
IP=$(curl -fsS https://api.ipify.org)
HOSTNAME="${IP//./-}.sslip.io"
echo "Free HTTPS hostname: $HOSTNAME"

sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
$HOSTNAME {
    @pnl {
        path /v1/pnl
        method GET
    }
    handle @pnl {
        reverse_proxy 127.0.0.1:8766
    }
    handle {
        respond 404
    }
}
EOF

sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
```

**Network:** open **TCP 80 and 443** in DigitalOcean's cloud firewall
(if enabled) and the VM firewall, but **never 8765 or 8766**.
Caddy automatically requests and renews HTTPS certificates when DNS
resolves and ports 80/443 are internet-accessible. If certificate
issuance fails, don't bypass browser TLS verification or switch the
GitHub Pages feed to HTTP.

Check the public endpoint from a browser or a different network:

```bash
curl -fsS "https://$HOSTNAME/v1/pnl"
```

Inspect: only `as_of_utc`, `markets` and `account` redacted
summary fields should appear; **no credentials, balances, cash
history, player names or exchange IDs**.

## Step 5 — connect GitHub Pages once HTTPS works

`dashboard/live-pnl-source.json` is a public non-secret configuration:

```json
{
  "api_url": "https://YOUR-PUBLIC-IP-WITH-DASHES.sslip.io/v1/pnl"
}
```

Commit the actual hostname after the URL has been checked from outside
the Droplet. The dashboard already polls this HTTPS URL every
**15 seconds**, shows FUNDED ACCOUNT, NFL, NBA settled P&L, and hides
unavailable/stale reads instead of pretending a past green number is
current. No per-settlement GitHub commits are required.

## Rollback and operational warnings

- Disable **read-only feed only**:
  `sudo systemctl disable --now market-maker-live-pnl.service`
- Disable/undo the *specific* Caddy site only after inspecting other
  hosted sites. Never indiscriminately stop an existing shared proxy.
- Revert `dashboard/live-pnl-source.json` to `"api_url": ""` if
  you no longer want public account P&L.
- SSLIP DNS is public and a certificate may expose the hostname in
  certificate-transparency logs. **The P&L aggregates are public**.
- No service above enables real-money trading or alters position/risk
  caps. Existing trading timers remain as they were.
