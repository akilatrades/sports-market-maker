# Security

This repository is public and controls bots that trade a real Kalshi
account, so it is set up to keep the account and the server out of reach of
anyone reading or contributing to the code.

- **No trading credentials in GitHub.** The Kalshi API key exists only on
  the server, in root-only settings files. GitHub holds an SSH key for the
  server's `trader` account. That account is not root, but it can deploy
  code and switch the bots on or off through two fixed helpers, so the key
  is treated like the Kalshi key: it belongs in a GitHub environment that
  only `main` can use ([setup](deploy/GITHUB_ACCESS.md#one-time-owner-setup-about-15-minutes)).
- **Owner-only server actions.** Go live / Stop, Deploy, diagnostics and the
  fill audit check who started them, run only from `main`, and only start by
  hand, never on a merge or schedule. Pull requests run tests without any
  secrets.
- **Public logs say little.** Server workflows print pass/fail results,
  on/off states, commit IDs and redacted aggregates; never keys, balances or
  order IDs.
- **Bounded risk.** Every order passes fixed per-order, per-game, per-team,
  nightly and account-wide limits, plus daily and total loss stops that
  block new orders.

Details: [deploy/GITHUB_ACCESS.md](deploy/GITHUB_ACCESS.md) (access and
secrets), [deploy/GO_LIVE_BUTTON.md](deploy/GO_LIVE_BUTTON.md) (the
Go live / Stop button) and
[docs/LIVE_ACCOUNT_SECURITY_CHECKLIST.md](docs/LIVE_ACCOUNT_SECURITY_CHECKLIST.md).

## Reporting a problem

If you find a security issue, please do not open a public issue. Use
GitHub's private vulnerability reporting (Security tab → *Report a
vulnerability*) or contact the owner through GitHub.
