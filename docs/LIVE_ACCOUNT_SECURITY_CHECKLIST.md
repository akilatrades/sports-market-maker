# Live-account security checklist (October 2026)

This public repository is research and executable trading code, not an
authenticated security audit. Public strategy code is **not** an API
credential. This checklist distinguishes verified source controls from
settings that must be verified on the owner's actual account and server.

## Code changes and source-verified protections

- Kalshi production signing material is loaded at runtime via environment
  variables, not published in the tracked source configuration.
- Current repository tracked-file names contain no obvious PEM/private-key
  or `.env` files. `.gitignore` now blocks common local credential files,
  but ignoring does not remove previously committed material.
- The private account server listens on `127.0.0.1:8765` and exposes
  read-only paths; the public P&L service publishes intentionally redacted
  aggregates, not keys or orders.
- Hosted GitHub Actions no longer receives `KALSHI_PRIVATE_KEY` or
  `KALSHI_KEY_ID` through the credential-check workflow; it tests only
  the public market-data endpoint. The actual production credential check
  must be run on the owner's secured server.
- Manual-input research jobs now use environment variables, not direct
  shell interpolation, and the Odds API backtest command is allowlisted.
- Credential-check logs no longer echo key prefixes or raw API errors.
- CI has regression checks guarding these properties.

## OWNER ACTIONS — cannot be confirmed from source code

1. **GitHub account and permissions:** enable phishing-resistant 2FA
   (passkey/security key), review active sessions, repository collaborators,
   installed apps and fine-grained personal access tokens. Give nobody
   else write access to this repository: a modified executable fetched
   during a later server release could access runtime credentials.
   Collaborators work through forks and pull requests
   ([GITHUB_ACCESS.md](../deploy/GITHUB_ACCESS.md)). Scheduled data-only
   GitHub Actions still write to main.
2. **GitHub Actions secrets:** the four `DROPLET_*` secrets reach the
   server's `trader` account, which runs the funded bots and can switch
   them on or off through the sudo helpers, so treat them like the Kalshi
   key: keep them in the `funded-droplet` environment limited to `main`
   ([GITHUB_ACCESS.md](../deploy/GITHUB_ACCESS.md)). `ODDS_API_KEY` can stay
   a repository secret. Inspect/remove obsolete `KALSHI_PRIVATE_KEY` and
   `KALSHI_KEY_ID` secrets if they still exist.
   If the server's P&L publisher is set up, its `GITHUB_PNL_PUBLISH_TOKEN`
   (in `/etc/market-maker-pnl-publisher.env`) can write to this repository:
   keep it fine-grained, limited to this repository, with a short expiry.
   The hosted credential-check workflow no longer needs them. Ensure no
   other Actions workflow has been added that loads trading credentials.
   Review repository Security > Secret scanning alerts, including old
   commits. GitHub alerts cannot be read from this repository connector.
3. **Kalshi keys:** inspect live API keys and recent account order/fill
   activity. If there is any possibility a production signing key was
   exposed, revoke it and generate a new one; install the replacement
   privately on the Droplet before resuming trading. Never put keys,
   PEM contents, environment-file contents or access tokens in GitHub
   code, issues, support chats, or screenshots.
4. **DigitalOcean:** enable account 2FA; review Droplet SSH authorized
   keys, authentication logs, user accounts, the Cloud Firewall and
   listening network ports. Permit SSH only from approved addresses where
   workable. Confirm private account port `8765` is not routed through a
   public proxy, and public P&L port `8766` is reachable only through
   intended redacted reverse-proxy routes. Update system packages.
5. **Server permissions:** verify both production env files under
   `/etc/market-maker-prod-*.env` are only readable by their intended
   service account/root, that order journals are private, and services
   run as the unprivileged `trader` account. Never paste env-file contents
   into diagnostics.
6. **Funding impact:** a key rotation or firewall change might temporarily
   stop the production bot. Schedule these changes and verify signed
   read-only preflights before starting live timers again.

## Limitations

We cannot inspect Droplet network services, SSH/host logs, Kalshi key
permissions, GitHub secret-scanning history or GitHub account access
from public repository source code alone. No sign of compromise is
not proof of no compromise. Do not claim the bot is impossible to hack.

If suspicious activity is detected: pause live bot timers, revoke
suspected API keys and GitHub access tokens, preserve audit logs,
secure the GitHub/DigitalOcean accounts, then reconcile Kalshi orders
and positions before re-arming.
