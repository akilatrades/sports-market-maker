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

if [[ "${1:-}" == "--off" ]]; then
  systemctl disable --now "$UNIT.timer" 2>/dev/null || true
  echo "Hourly private export is OFF. (Settings file kept: $ENV)"
  exit 0
fi

[[ -f "$ROOT/deploy/$UNIT.service" && -f "$ROOT/deploy/$UNIT.timer" ]] || {
  echo "Deploy the code with these files first (Deploy funded worker code)." >&2; exit 1; }

install -m 644 -o root -g root "$ROOT/deploy/$UNIT.service" "$ROOT/deploy/$UNIT.timer" /etc/systemd/system/
systemctl daemon-reload

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
