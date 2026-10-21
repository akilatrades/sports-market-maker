# One-click, code-only GitHub → DigitalOcean funded-worker releases

**State: installed and in use** (the *Deploy funded worker code* workflow).
This is a narrow release lane for
`/home/trader/sports-market-maker-prod-auto`, the separate funded-account
NBA/NFL checkout. It does **not** manage the legacy
`/home/trader/sports-market-maker` runner.

## Verified connection

The read-only GitHub Actions SSH preflight first succeeded on 2026-10-21 UTC.
Since then the funded bots have been switched on with the Go live button,
and the older `market-maker.timer` (whose `run.sh` used to `git pull`) has
been disabled. A successful SSH connection is NOT a production deployment,
signed Kalshi readiness check, or trading activation.

## Initial privileged setup — performed once by the owner

An account owner must review `deploy/smm-prod-release.sh` and
`deploy/install_github_release_helper.sh`, then install the limited root
helper **from a fixed, verified main-branch commit SHA**. Run the installer
from the DigitalOcean root console after its PR has passed CI and merged.

Example structure (replace `REVIEWED_40_CHARACTER_SHA` with the actual
main-branch commit):
```bash
curl --proto '=https' --tlsv1.2 -fsSL \
  https://raw.githubusercontent.com/akilatrades/sports-market-maker/REVIEWED_40_CHARACTER_SHA/deploy/install_github_release_helper.sh \
  -o /tmp/smm-install-release.sh
bash /tmp/smm-install-release.sh REVIEWED_40_CHARACTER_SHA
rm /tmp/smm-install-release.sh
```
Do not run that example with its placeholder. Verify the SHA in GitHub
first. This installer downloads the helper from the same pinned commit,
checks syntax, writes a root-owned executable to
`/usr/local/sbin/smm-prod-release`, and grants the existing `trader`
account sudo permission to invoke **only that fixed helper path**.
It does **not** install production keys, enable timers, or submit orders.

The GitHub secrets `DROPLET_HOST`, `DROPLET_USER`,
`DROPLET_SSH_KEY` and `DROPLET_KNOWN_HOSTS` remain private, in the
`funded-droplet` environment ([GITHUB_ACCESS.md](GITHUB_ACCESS.md)). Do not send
private SSH keys or Kalshi credentials through chat, GitHub commits,
workflow inputs or issue screenshots.

## Each future code release — no DigitalOcean console

In GitHub Actions select **Deploy funded worker code → Run workflow**
on **main**, select:
- `CHECK_ONLY`: full CI then a read-only SSH check; no remote mutation.
- `DEPLOY_CODE`: full CI on Python 3.11 and 3.12, JS and shell tests,
  then connect through pinned SSH host identity and invoke the fixed helper.

The helper deploys exactly the commit the workflow ran from, which must be
on `main`, and requires a clean tracked production checkout. It records the originally active funded timers,
stops **both funded timers**, waits for executing workers to finish,
fast-forwards the separate funded checkout, validates low-memory syntax,
and (when originally live) runs signed GET-only account preflights. It
restores **only timers already active before the deployment**; an inactive
NBA/NFL bot is never armed. It also refuses dependency and funded systemd
unit changes, never overwrites KILL files, journals, credentials or risk
flags, and never explicitly triggers an order-submitting service.

If verification fails, it tries to restore the original code and timer
states; if rollback cannot be verified, it leaves the funded timers
stopped for owner inspection. Signed-account validation logs are retained
root-only on the Droplet after failure and never printed into the public
GitHub Actions logs. On success GitHub verifies the resulting SHA.

## Scope limits

- **No automatic production deployment on push.** Each code release is
  deliberately requested by the owner via the GitHub Actions button.
  This prevents unreviewed changes to a real-money system.
- The older general `market-maker.timer` and `run.sh` are disabled on the
  server; this workflow never touches them.
- A workflow success does not prove strategy profitability, exchange fills,
  ongoing bot uptime, or fresh odds. A failed preflight means no release.
- Model input synchronization and GitHub Pages publishing are distinct from
  deploying executable trading code.
- Changes to Python dependencies, timer/service definitions, activation
  flags, or funded-account risk settings require a separate reviewed release
  and explicit owner decision. Do not bypass the restrictions to get a green
  badge.
