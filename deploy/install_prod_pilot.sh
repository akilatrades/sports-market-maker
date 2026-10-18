#!/usr/bin/env bash
# Installs *only* a keyless read-only production scanner plus a disabled
# one-shot live unit. It NEVER starts the live unit or touches the Demo timer.
set -Eeuo pipefail
test "$(id -u)" -eq 0 || { echo "Must run as root"; exit 1; }
R=/home/trader/sports-market-maker-prod
if [ -e "$R" ]; then
  echo "Separate production checkout exists; refusing to overwrite it."
  echo "Review it manually before updating."
  exit 1
fi
id trader >/dev/null
sudo -u trader git clone --depth 1 https://github.com/akilatrades/sports-market-maker.git "$R"
sudo -u trader python3 -m venv "$R/.venv"
sudo -u trader "$R/.venv/bin/python" -m pip install -q -r "$R/requirements.txt"
install -m 644 "$R/deploy/market-maker-prod-nfl-dry.service" /etc/systemd/system/market-maker-prod-nfl-dry.service
install -m 644 "$R/deploy/market-maker-prod-nfl.service" /etc/systemd/system/market-maker-prod-nfl.service
systemctl daemon-reload
echo "Installed production pilot services (NO live orders submitted)."
echo "Running READ-ONLY production opportunity check:"
systemctl start market-maker-prod-nfl-dry.service
journalctl -u market-maker-prod-nfl-dry.service -n 30 --no-pager
echo "Production LIVE service remains unstarted. Create a SEPARATE root-only"
echo "/etc/market-maker-prod.env with PROD keys only after checking dry-run results."
