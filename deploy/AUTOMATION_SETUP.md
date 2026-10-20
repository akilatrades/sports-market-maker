# GitHub Actions → DigitalOcean: staged connection

This is the **first, read-only stage** of deployment automation for the existing
Ubuntu Droplet. The workflow `.github/workflows/droplet-preflight.yml` is
manual (`workflow_dispatch`). It does **not** install code, stop/start services,
read Kalshi credentials, change risk, or place/cancel any orders. It reports
the deployed SHA, systemd states and whether the installed `run.sh` still
auto-pulls GitHub code.

## Important existing behavior

`deploy/install.sh` writes `/home/trader/run.sh`, which currently invokes
`git pull -q --rebase origin main || true` before trading every minute. If
that installed file still has this logic, production can change after any
`main` push without an approved deployment. A controlled release pipeline
must first **retire auto-pull**, avoid concurrent checkout with live workers,
and preserve all existing Kalshi environment files, journals and emergency
stops. Do not turn on automatic deploys until that migration is validated.

## One-time secure SSH setup (account owner)

The goal is to do this once, not on each code change.

1. On your own computer, generate a dedicated Ed25519 key pair for GitHub Actions
   (`ssh-keygen -t ed25519 -f <chosen-private-key-path> -C smm-actions`).
   **Never send the private key through chat or commit it to the repository.**
2. Install **only the public key** in
   `/home/trader/.ssh/authorized_keys` on the Droplet; owner `trader`,
   directory mode 700, file mode 600. Use a distinct key, not the one used
   for personal administrator access.
3. On the Droplet, obtain its **public** host identity using
   `cat /etc/ssh/ssh_host_ed25519_key.pub`. Compare its fingerprint with
   a known-good source or the Droplet console before pinning. Compose a
   `known_hosts` line:
   `<Droplet-hostname-or-IP> ssh-ed25519 <public-host-key-base64>`.
   Never use an unverified `ssh-keyscan` result as the sole host validation.
4. In repository **Settings → Secrets and variables → Actions**, add secrets:
   - `DROPLET_HOST`: Droplet IP/hostname (no scheme).
   - `DROPLET_USER`: `trader`, not `root`.
   - `DROPLET_SSH_KEY`: contents of the dedicated **private** Ed25519 key.
   - `DROPLET_KNOWN_HOSTS`: verified complete `known_hosts` line.
5. In GitHub **Actions → Droplet read-only preflight → Run workflow**, choose
   the audited branch (until merged) and run. The job must only report service
   states and commit ID; it should not modify the Droplet.

If port 22 is firewalled to exclude GitHub Actions, this job will fail. Do
not broadly expose SSH to the Internet without considering a more restricted
transport; a self-hosted runner, VPN or pull-based approved-release agent may
be preferable.

## Phase two — NOT implemented or activated here

After a successful read-only preflight, implement a separately reviewed,
approval-gated release workflow that:
- runs the full test matrix (Python, shell, dashboard),
- selects an immutable commit SHA,
- uses a least-privilege deployment identity,
- coordinates a deployment lock and timer handoff,
- never overwrites `/etc/market-maker.env` or owned trading journals,
- preflights the environment, proves which SHA is deployed, and
- stops and reports failures without silently treating them as success.

Deployment must not re-arm an inactive production trader, change order/stop
settings, or expand risk limits. Existing resting positions and cancellation
policies need explicit consideration before maintenance windows.

**As of this file, no automated production deployment is installed.**
