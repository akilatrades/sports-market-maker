# Security

This repository is public and controls bots that trade a real Kalshi
account, so it is set up to keep the account and the server out of reach of
anyone reading or contributing to the code.

- **No trading credentials in GitHub.** The Kalshi API key exists only on
  the server, in root-only settings files. GitHub holds only an SSH key for
  an unprivileged server account, kept in a GitHub environment that only
  `main` can use.
- **Owner-only server actions.** Go live / Stop, Deploy, diagnostics and the
  fill audit check who started them and run only from `main`. Pull requests
  run tests without any secrets.
- **Public logs say little.** Server workflows print only PASS/FAIL, on/off
  states and commit IDs.
- **Bounded risk.** Every order passes fixed per-order, per-game, per-team,
  nightly and account-wide limits, plus daily and total loss stops that shut
  the bots off.

Details: [deploy/GITHUB_ACCESS.md](deploy/GITHUB_ACCESS.md) (access and
secrets), [deploy/GO_LIVE_BUTTON.md](deploy/GO_LIVE_BUTTON.md) (the
Go live / Stop button) and
[docs/LIVE_ACCOUNT_SECURITY_CHECKLIST.md](docs/LIVE_ACCOUNT_SECURITY_CHECKLIST.md).

## Reporting a problem

If you find a security issue, please do not open a public issue. Use
GitHub's private vulnerability reporting (Security tab → *Report a
vulnerability*) or contact the owner through GitHub.
