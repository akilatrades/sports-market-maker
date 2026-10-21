# Go live / Stop button for the funded NBA + NFL bots

A GitHub Actions button that switches the funded bots on or off on the
DigitalOcean Droplet, so day-to-day control needs no console.

| Action | What it does |
|---|---|
| `STATUS` | Read-only: deployed commit, timer on/off, KILL switches, arm flags (yes/no) |
| `GO_LIVE` | Runs the full test suite, checks the Droplet runs this commit's trading code, runs signed read-only account checks, arms both bots for shared-account trading, enables both timers |
| `STOP` | Stops and disables both timers. No new orders; orders already resting expire at tip-off |
| `STOP_AND_CANCEL` | `STOP`, then a KILL pass that cancels only the bots' own resting orders |

Every action except `STATUS` requires typing the action name again in the
**confirm** box. Only the repository owner can run it, and only from `main`.

## What it never shows

This repository and its Actions logs are public. The Droplet helper prints
only step names, PASS/FAIL, timer states and the deployed commit. It never
prints the settings files, keys, host address, balances, positions, tickers
or order IDs. Full output of each account check is kept on the Droplet in
root-only files under `/root/smm-control-logs/`. SSH secrets stay in
GitHub's encrypted secrets and are masked in logs.

## One-time setup (owner, DigitalOcean root console)

Uses the same four SSH secrets as the existing release workflow
(`DROPLET_HOST`, `DROPLET_USER`, `DROPLET_SSH_KEY`, `DROPLET_KNOWN_HOSTS`).
Replace `REVIEWED_40_CHARACTER_SHA` with the main commit that contains this
file, verified on GitHub:

```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/akilatrades/sports-market-maker/REVIEWED_40_CHARACTER_SHA/deploy/install_github_control_helper.sh \
  -o /tmp/smm-install-control.sh
bash /tmp/smm-install-control.sh REVIEWED_40_CHARACTER_SHA
rm /tmp/smm-install-control.sh
```

It installs `/usr/local/sbin/smm-prod-control` (root-owned) and a sudoers
rule allowing the `trader` account to run only that path. It changes no
timers, orders, credentials or risk settings. To update the helper later,
rerun with a newer reviewed SHA and `--replace`.

## Going live

1. **Deploy funded worker code** with `DEPLOY_CODE` (puts the current code on
   the Droplet; never switches a bot on).
2. **Go live / Stop funded bots** with `GO_LIVE`, typing `GO_LIVE` to confirm.

`GO_LIVE` refuses, and leaves both bots off with settings unchanged, if:
the deployed trading code differs from the commit you ran it from; a KILL
switch is present; a settings file or journal is missing; the owner
production settings (`KALSHI_ENV`, `TRADE_MODE`, `ALLOW_PRODUCTION_TRADING`,
`PROD_AUTO_ARM` for NFL, `TRADE_MARKET` for NBA) are not already in place; or
a signed account check fails. If a check fails after arming, the settings
files are restored from a backup and both timers are disabled.

It sets only `SMM_DUAL_MARKET=YES` (both bots) and `PROD_NBA_AUTO_ARM=YES`
(NBA), plus the shared-account marker, exactly as
`deploy/activate_dual_market.sh` does. Keys, other flags and all risk limits
are untouched. The NBA readiness check needs verified projection rows, so on
a day with no NBA games `GO_LIVE` fails safely; run it again on a game day.

## Root safety

The helper runs from `/` with a fixed `PATH` and isolated Python (`-I`), so
nothing the `trader` account controls is imported or executed as root.
Repository code (checks, workers) only ever runs as `trader`. The KILL file
for a cancel pass is written by `trader`, never by root, and a KILL file that
is a link is refused.

**Secrets:** the `control` job uses the `funded-droplet` GitHub environment.
Once the four `DROPLET_*` secrets are moved into it and limited to `main`
(steps in [GITHUB_ACCESS.md](GITHUB_ACCESS.md)), no branch other than `main`
can reach the server. Adding yourself as a required reviewer is optional; each
Go live / Stop would then also need an approval click in GitHub.

## Stopping

`STOP` disables both timers (they stay off after a reboot) and then
confirms both are off; if either is still on it reports a failure rather
than success. It waits up to five minutes for a running deploy to finish,
and a Go live test run never holds it up. `STOP_AND_CANCEL` also places a
KILL switch, runs each worker once so it cancels its own resting orders,
then removes only the KILL switches it created. If a cancel pass fails, the
switches stay and the log says to check Kalshi directly. Stopping never
cancels orders placed by hand or by anything else.
