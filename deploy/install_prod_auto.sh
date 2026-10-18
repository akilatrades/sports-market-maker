#!/usr/bin/env bash
# Safe installer: only creates a separate checkout and installs disabled units.
# Does not install credentials, place orders, or enable the production timer.
set -Eeuo pipefail
if [[ "$(id -u)" != "0" ]]; then
  echo "Run as root."
  exit 1
fi
ROOT=/home/trader/sports-market-maker-prod-auto
if [[ -e "$ROOT" ]]; then
  echo "Separate auto checkout exists. Refusing to overwrite."
  exit 1
fi
id trader >/dev/null
sudo -u trader git clone --depth 1 https://github.com/akilatrades/sports-market-maker.git "$ROOT"
sudo -u trader python3 -m venv "$ROOT/.venv"
sudo -u trader "$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"
install -m 644 "$ROOT/deploy/market-maker-prod-nfl-auto.service" /etc/systemd/system/
install -m 644 "$ROOT/deploy/market-maker-prod-nfl-auto.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl disable --now market-maker-prod-nfl-auto.timer >/dev/null 2>&1 || true
echo "SAFE: Production auto files installed. Real-money timer DISABLED."
echo "SAFE: Existing Demo service/timer untouched."
echo "Running read-only live production market scan (NO credentials needed):"
cd "$ROOT"
sudo -u trader env KALSHI_ENV=prod TRADE_MODE=dry "$ROOT/.venv/bin/python" -m live.prod_nfl_auto --dry-run
echo "Configure separate /etc/market-maker-prod-auto.env only after inspecting quote"
echo "and strategy safeguards. NEVER paste production credentials into chat."
