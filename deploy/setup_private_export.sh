#!/usr/bin/env bash
# One-time owner setup for the private fills export (deploy/PRIVATE_FILL_EXPORT.md).
# Run as root in the DigitalOcean console:
#   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_private_export.sh
# First run: installs the timer (off) and creates the settings file.
# After pasting the token: run again; it tests one export and turns the timer on.
#   ... setup_private_export.sh --off   turns the hourly export off again.
# Never touches the trading bots, their timers, journals or Kalshi settings.
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "Run with sudo" >&2; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
ENV=/etc/market-maker-private-export.env
UNIT=market-maker-private-export
tgit() { runuser -u trader -- git -C "$ROOT" "$@"; }

if [[ "${1:-}" == "--off" ]]; then
  systemctl disable --now "$UNIT.timer"
  systemctl stop "$UNIT.service"
  echo "Hourly private export is OFF. (Settings file kept: $ENV)"
  exit 0
fi

# Never run while a code release is changing the checkout.
exec 9>/run/lock/smm-production-release.lock
flock -n 9 || { echo "A code release is running; try again in a few minutes." >&2; exit 1; }

# Install the units from GitHub main (guards against accidental edits to the
# copies on this server).
case "$(tgit remote get-url origin)" in
  https://github.com/akilatrades/sports-market-maker|https://github.com/akilatrades/sports-market-maker.git) ;;
  *) echo "The checkout's origin is not the project repository; refusing." >&2; exit 1 ;;
esac
[[ -z "$(tgit status --porcelain --untracked-files=no)" ]] || {
  echo "The server checkout has local changes; refusing. Deploy cleanly first." >&2; exit 1; }
tgit fetch --quiet origin main
for f in "$UNIT.service" "$UNIT.timer"; do
  tgit cat-file -e "FETCH_HEAD:deploy/$f" 2>/dev/null || {
    echo "deploy/$f is not on GitHub main yet: merge the pull request first." >&2; exit 1; }
  tgit show "FETCH_HEAD:deploy/$f" > "/etc/systemd/system/$f"
  chown root:root "/etc/systemd/system/$f"
  chmod 644 "/etc/systemd/system/$f"
done
[[ -f "$ROOT/tools/export_private_fills.py" ]] || {
  echo "Deploy the code first (Deploy funded worker code -> DEPLOY_CODE)." >&2; exit 1; }
systemctl daemon-reload
echo "Units installed from GitHub main $(tgit rev-parse --short FETCH_HEAD); server code at $(tgit rev-parse --short HEAD)."

if [[ ! -f "$ENV" ]]; then
  install -m 600 -o root -g root /dev/null "$ENV"
  printf 'PRIVATE_EXPORT_REPO=akilatrades/smm-private-data\nPRIVATE_EXPORT_TOKEN=\n' > "$ENV"
fi
chown root:root "$ENV"
chmod 600 "$ENV"

if ! grep -Eq '^PRIVATE_EXPORT_TOKEN=.{20,}$' "$ENV"; then
  echo "STEP 1 DONE. Now open the settings file:"
  echo "  sudo nano $ENV"
  echo "Paste the GitHub token right after PRIVATE_EXPORT_TOKEN= (no spaces),"
  echo "check the repo name, save (Ctrl+O, Enter) and exit (Ctrl+X)."
  echo "Then run this script again."
  exit 0
fi

echo "Testing one export now..."
if systemctl start "$UNIT.service"; then
  journalctl -u "$UNIT.service" -n 3 --no-pager -o cat | grep -v TOKEN || true
  systemctl enable --now "$UNIT.timer"
  echo "OK: export works and now runs every hour (about :52 past)."
else
  journalctl -u "$UNIT.service" -n 5 --no-pager -o cat | grep -E "PRIVATE EXPORT FAILED" || true
  echo "Export failed (reason above). The timer was NOT turned on." >&2
  echo "Common fixes: token pasted wrongly, repo name wrong, repo not private," >&2
  echo "repo created without a README, or token lacks Contents: Read and write." >&2
  exit 1
fi
