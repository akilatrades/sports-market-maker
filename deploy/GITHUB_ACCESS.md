# GitHub access and server secrets

The repository is public. The code, documentation, research data and
dashboard are meant to be read by anyone. The trading account and the server
are not, and this page explains how the two are kept apart.

## What is public, and what is not

| Public (in the repository) | Never in the repository |
|---|---|
| All code, tests and documentation | The Kalshi API key (only on the server, in root-only settings files) |
| Research data and backtest outputs | The server's SSH key (a GitHub secret) |
| Dry-run order logs and the public dashboard | The Odds API key (a GitHub secret) |
| The server's address (the dashboard's live P&L feed is served from it) | Raw sportsbook and Databento data (licensed, not redistributable) |
| GitHub Actions logs (server jobs print pass/fail, on/off states, commits and redacted aggregates; never keys, balances or order IDs) | |

On 2026-10-21 the full history (863 commits, every branch) was scanned with
[gitleaks](https://github.com/gitleaks/gitleaks): no keys, tokens or private
keys were found.

## Who can do what

- **Anyone** can read the code, fork it and open a pull request. Checks on
  pull requests run without any secrets.
- **Only the owner** can run the server workflows (Go live / Stop, Deploy,
  diagnostics and the fill audit), and they run only from `main` and only
  when started by hand. The workflows that spend Odds API credits are
  owner-only too.
- **Nobody else ever gets:** the Kalshi login or API key, the DigitalOcean
  login, the owner's GitHub login, the server SSH key, or write access to
  this repository.

### Why not write access?

In a personal GitHub repository, anyone with write access can push to `main`
and run workflows, and a workflow can read the repository's secrets. One of
those secrets is the SSH key for the server that runs the funded bots. So
write access would, in practice, give someone the trading account. The
checks in the workflow files stop mistakes, but a person with write access
could edit the files themselves.

If the project becomes a business, revisit this: move the repository into a
GitHub organization (which can restrict who pushes to `main`), or keep the
live trading code in a separate private repository.

## Adding a collaborator: fork and pull request

1. They fork `akilatrades/sports-market-maker`, clone their fork, make a
   branch and open a pull request into `main`.
2. `.github/CODEOWNERS` requests the owner's review automatically. Read the
   whole change.
3. Merge only what you understand. A merge by itself never starts anything
   on the server. But code on `main` **does** run on the server the next time
   you press a server button: *Deploy* installs `live/`, `kalshi/`,
   `markets/` and `tools/`; the fill audit and diagnostics run scripts from
   `tools/` and `deploy/`. So review a change to any of those folders, or to
   `.github/`, as if it will run next to the trading account.

See [CONTRIBUTING.md](../CONTRIBUTING.md) for the contributor side.

## One-time owner setup (about 15 minutes)

These are GitHub and server settings, so they cannot be changed from the
repository.

1. **Fork pull requests:** Settings → Actions → General → approval for fork
   pull request workflows → choose the strictest option (approval for all
   outside contributors). Their checks then wait for your click.
2. **Create the environment:** Settings → Environments → New environment →
   name it `funded-droplet`. Under *Deployment branches and tags* choose
   *Selected branches and tags* and add `main`. Leave *Required reviewers*
   off, unless you want an extra approval click on every server action,
   including Stop. (If a server workflow runs before you do this, GitHub
   creates the environment automatically; just add the `main` rule.)
3. **Put the four server secrets in it** (*Add environment secret*):
   `DROPLET_HOST`, `DROPLET_USER` (`trader`), `DROPLET_KNOWN_HOSTS` and
   `DROPLET_SSH_KEY`. GitHub never shows a saved secret again, so either:
   - paste the same values, if you still have the private key file from
     [AUTOMATION_SETUP.md](AUTOMATION_SETUP.md), or
   - **make a new key (recommended):** on your computer run
     `ssh-keygen -t ed25519 -N "" -f smm-actions-2 -C smm-actions-2`, add the
     `.pub` line to `/home/trader/.ssh/authorized_keys` from the
     DigitalOcean console, and paste the private key into `DROPLET_SSH_KEY`.
     (`-N ""` gives the key no passphrase, which GitHub Actions needs;
     `smm-actions-2` labels it so you can tell it from the old key.)
     `DROPLET_KNOWN_HOSTS` is one line: the server address, a space, then
     the output of `cat /etc/ssh/ssh_host_ed25519_key.pub` on the server.
4. Run **Go live / Stop funded bots → STATUS**. It must pass.
5. **Delete the four repository-level secrets** (Settings → Secrets and
   variables → Actions → Repository secrets). If you made a new key, also
   delete the old key's line from `authorized_keys`: the one that does
   **not** end in `smm-actions-2` (it ends in `smm-actions` if you followed
   [AUTOMATION_SETUP.md](AUTOMATION_SETUP.md)).
6. Run **STATUS** again. If it passes, only jobs that run from `main` and
   name `funded-droplet` can reach the server.
7. **Private security reports:** Settings → Security → turn on *Private
   vulnerability reporting*, which [SECURITY.md](../SECURITY.md) points to.

The Odds API key can stay a repository secret: the worst misuse is spent
credits, and the scheduled data jobs need it.

## Server checks (DigitalOcean console)

The server's address is public, because the dashboard's live P&L feed is
served from it. That is fine if the server only accepts keys and opens only
the ports it needs. Check once:

```bash
sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin)'
ss -tlnp
```

- You want `passwordauthentication no`, `kbdinteractiveauthentication no`
  and `permitrootlogin prohibit-password` (keys only). Do not set
  `permitrootlogin no`: DigitalOcean's web console logs in as root over SSH,
  so that would lock you out of the console these steps use. If you change
  any SSH setting, keep the current session open and test a new login
  before closing it.
- Only SSH (22) and the HTTPS proxy (80/443) should listen on public
  addresses. The account dashboard (8765) must listen on `127.0.0.1` only.
- Optional: a DigitalOcean cloud firewall allowing inbound 22, 80 and 443
  only.
