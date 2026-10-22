# Operations guide

How the live system runs. Everything here is owner-run; nothing in this
repository changes the server on its own.

## What runs where

| Where | What |
|---|---|
| GitHub Actions | Tests, data refreshes, model projections, sportsbook lines, research jobs, the public dashboard |
| DigitalOcean server (Ubuntu) | The funded NBA and NFL order workers (`live/prod_nba_auto.py`, `live/prod_nfl_auto.py`), each run by a systemd timer |
| DigitalOcean server (Ubuntu) | The spread maker pilot (`live/prod_spread_auto.py`): shadow ledger, and live quotes only after the owner arms it. Setup and switches: [PROD_SPREAD_AUTO.md](PROD_SPREAD_AUTO.md) |
| Kalshi | The exchange; the workers use a signed API key stored only on the server |
| Private GitHub repo (`smm-private-data`, optional) | Hourly copy of the bots' live orders, fills and settlements from their journals, so they can be studied without the Kalshi key leaving the server. Setup: [PRIVATE_FILL_EXPORT.md](PRIVATE_FILL_EXPORT.md) |

Credentials live only in root-owned files on the server (`/etc/market-maker-*.env`)
and are never committed, printed or sent to GitHub.

## Releasing code

GitHub → Actions → **Deploy funded worker code**:

- `CHECK_ONLY` runs the tests and a read-only server check.
- `DEPLOY_CODE` runs the full tests, then updates the server to the exact
  tested commit. Timers that were on are switched back on after signed
  read-only account checks pass; timers that were off stay off.

Details: [GITHUB_PRODUCTION_RELEASE.md](GITHUB_PRODUCTION_RELEASE.md).

## Going live and stopping

GitHub → Actions → **Go live / Stop funded bots** (owner only; type the
action name to confirm):

| Action | Effect |
|---|---|
| `STATUS` | Shows the deployed commit and whether each bot is on; changes nothing |
| `GO_LIVE` | Checks code, settings and the account, then switches both bots on |
| `STOP` | Switches both bots off; resting orders expire at tip-off |
| `STOP_AND_CANCEL` | Switches both bots off and cancels their resting orders |

This workflow controls the NBA and NFL bots only. The spread maker pilot has
its own owner script (`deploy/setup_spread_maker.sh --disarm`, `--cancel`,
`--off`); the account loss stops apply to all three bots.

Public logs show only pass/fail and on/off. Details:
[GO_LIVE_BUTTON.md](GO_LIVE_BUTTON.md).

## Limits

Current per-order, game, team, daily, lifetime and loss limits are in
[PROD_NBA_AUTO.md](PROD_NBA_AUTO.md#execution-policy) (NBA) and
[PROD_NFL_AUTO.md](PROD_NFL_AUTO.md) (NFL). Both bots also share
account-wide caps (`live/shared_account_risk.py`).

## Monitoring on the server

```bash
systemctl list-timers 'market-maker-prod-*'
journalctl -u market-maker-prod-nba-auto.service -n 70 --no-pager
cat /home/trader/prod-nba-auto/last_scan.json
```

Every worker pass first reconciles resting orders, positions and fills with
the exchange and stops if anything is unexplained. Each order is written to
a journal before it is sent.

## Other procedures

| Document | Purpose |
|---|---|
| [PROD_NBA_AUTO.md](PROD_NBA_AUTO.md) | NBA worker rules, preflight and limits |
| [PROD_NFL_AUTO.md](PROD_NFL_AUTO.md) | NFL worker rules and limits |
| [DUAL_MARKET_PRODUCTION.md](DUAL_MARKET_PRODUCTION.md) | Running NBA and NFL on one account |
| [ACCOUNT_DASHBOARD.md](ACCOUNT_DASHBOARD.md) | Private read-only account view |
| [PUBLIC_PNL_REFRESH.md](PUBLIC_PNL_REFRESH.md) | Publishing verified P&L to the public dashboard |
| [LIVE_ACCOUNT_PNL.md](LIVE_ACCOUNT_PNL.md) | Near-live settled P&L feed for the dashboard |
| [GITHUB_ACCESS.md](GITHUB_ACCESS.md) | What is public, who can run what, adding a collaborator, moving server secrets into the `funded-droplet` environment |
| [AUTOMATION_SETUP.md](AUTOMATION_SETUP.md) | One-time GitHub-to-server SSH setup |
| [PROD_NFL_PILOT.md](PROD_NFL_PILOT.md) | The first supervised NFL order (historical) |
| [NFL_WORKER_MEMORY.md](NFL_WORKER_MEMORY.md) | Incident note |

## Legacy research runner

An older general trader (`live/nba_trade.py`, installed by `install.sh`)
is **retired on the server**: its `market-maker.timer` is disabled, and the
trader refuses to send live orders to the production exchange. GitHub's
*nba trade (dry run)* and *nfl trade (dry run)* workflows still run it in dry mode to publish the
order logs in `outputs/live/`. It is separate from the funded workers above.
