# Production P&L refresh: what is public and what is private

**No trading permissions and no exposure of balances/positions.**

## The issue this fixes

The public recruiter-facing dashboard previously loaded a historical JSON
file, `outputs/dashboard/production_pnl.json`, only on page load. The
2026-10-19 01:34 UTC saved report said NFL **+$1.99 from two settled
markets** while other owned NFL orders were still awaiting settlement.
It was a valid **as-of snapshot**, but after a later Matthew Golden loss
it was wrong to make it look like *current* positive trading P&L.

The public page now polls the live server feed **every 15 seconds** and shows
**an em dash, not a stale green profit**, whenever the report is older than
**90 seconds** (live feed) or **15 minutes** (committed snapshot). A failure does not silently
substitute simulation or infer a zero-dollar balance.

The private `http://127.0.0.1:8765/` account dashboard already
uses a signed **GET-only** Kalshi collector on the Droplet, with a
one-minute refresh; it also now hides P&L if the collector stops.
It is accessible only through the owner's SSH tunnel and is the faster
source of truth. No production Kalshi key should ever be embedded in
GitHub Pages JavaScript or committed to the repository.

## Getting the Matthew Golden loss into the verified total

*Historical (19 October): at the time NFL was stopped and NBA not yet live.
Today the bots run together and code reaches the server only through
*Deploy funded worker code*; do not `git pull` in the funded checkout.*

Use the same droplet **with NFL currently stopped and NBA still
inactive**. Update the checkout only when no live service is executing
code that could change during the update. Then generate a redacted
signed report without any GitHub write:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader git pull --ff-only origin main

sudo systemd-run --wait --pipe --collect \
  --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile=/etc/market-maker-prod-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m tools.publish_production_pnl
```

This prints **only** redacted NFL and NBA totals and source timestamps,
never balances, raw fills, tickers, account IDs or order IDs. Paste that
redacted output into chat if investigation is required; do not paste
the env file or private journal.

- A `verified_snapshot` figure includes exchange settlements matched
  to the owner's accepted orders and independently checked owned fill
  costs. All unsettled positions are excluded from *realized* P&L.
- If the Golden market has settled at a loss, the new signed aggregate
  **should decrease** the net NFL realized profit without hand editing.
- If the exchange has not returned the settlement, or its market costs
  do not reconcile, the exporter refuses to claim updated P&L.
- The $1.99 value in the historical record must not be guessed away;
  only signed exchange accounting can determine the correct new total.
- The unauthenticated public JSON is NEVER accepted as a source for
  real-money trading decisions or account risk calculations.

## Optional automated public publishing (10–15-minute snapshots)

**The owner must explicitly approve publishing aggregate realized NFL
and NBA P&L to a publicly readable GitHub Pages site.** The script is
read-only to Kalshi, but writes the **aggregate JSON** to one GitHub
file. It does not update risk limits, place trades, enable NBA or
cancel orders. No individual traders' accounts or fills are shared.

1. In your GitHub settings create a **fine-grained personal access
   token** with access ONLY to `akilatrades/sports-market-maker`,
   **Contents: Read and write**. Keep a short expiration, use a
   dedicated token, and do not enable permissions for other repos.
   Never paste it in chat.
2. On the Droplet, enter `GITHUB_PNL_PUBLISH_TOKEN=<value>` in
   a NEW root-owned file `/etc/market-maker-pnl-publisher.env`
   (permissions **0600**). This is a separate secret from the
   Kalshi credentials and is NEVER committed. Do not put tokens on
   a command line, in git remotes, public URLs or shell history.
3. Inspect `deploy/market-maker-pnl-publisher.service` and
   `.timer`. Copy them into `/etc/systemd/system/` as root, then
   run `systemctl daemon-reload`.
4. Start ONE controlled publisher pass with
   `systemctl start market-maker-pnl-publisher.service`. Verify
   `systemctl status ...` shows success and confirm the *public
   JSON* contains only timestamped two-cohort aggregates. If a
   reconciliation check fails, do not override it.
5. **Only after the dry run and first publication pass both work,**
   `systemctl enable --now market-maker-pnl-publisher.timer`.
   The timer checks approximately every **10 minutes** and refreshes
   the published snapshot with a new GitHub commit. GitHub Pages
   deployment introduces additional delay. GitHub Actions jobs can
   queue, and the public number will disappear if it becomes stale.
6. Stop public uploads at any time using
   `systemctl disable --now market-maker-pnl-publisher.timer`.
   Revoke the token in GitHub to remove publisher access.

**Important operational trade-off:** repeated commits produce Git
history and trigger GitHub Pages deployments. This is an opt-in
near-live **public aggregate reporting** design, not tick-level
streaming. For current account P&L, the SSH-tunneled private view
remains preferable.

## Observed assertions and tests

`python -m pytest tests/test_publish_production_pnl.py` verifies a
**negative** settlement can replace an earlier positive historical
snapshot, that NFL and NBA cannot cross-contaminate totals, that
unknown fill ownership/costs halt publication and that public
aggregate JSON excludes private names, IDs and balances.

`tools/publish_production_pnl.py` uses
`live.account_dashboard.ReadOnlyClient`, which rejects all non-GET
methods. No repo workflow stores Kalshi production keys.

**Never connect this public publisher to the order-entry path.**
