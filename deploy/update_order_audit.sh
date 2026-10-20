#!/usr/bin/env bash
# One-step, read-only Kalshi order-history dashboard deployment.
# Trading limits, credentials, settlement P&L and kill switches stay unchanged.
set -Eeuo pipefail
[[ $(id -u) -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
cd /home/trader/sports-market-maker-prod-auto

nfl_was=0
nba_was=0
dashboard_was=0
systemctl is-active --quiet market-maker-prod-nfl-auto.timer && nfl_was=1
systemctl is-active --quiet market-maker-prod-nba-auto.timer && nba_was=1
systemctl is-active --quiet market-maker-dashboard.service && dashboard_was=1

restore() {
  status=$?
  trap - EXIT
  if (( dashboard_was )); then
    systemctl restart market-maker-dashboard.service || echo "Private dashboard restart failed." >&2
  fi
  if (( nfl_was )); then systemctl start market-maker-prod-nfl-auto.timer; fi
  if (( nba_was )); then systemctl start market-maker-prod-nba-auto.timer; fi
  exit "$status"
}
trap restore EXIT

systemctl stop market-maker-prod-nfl-auto.timer market-maker-prod-nba-auto.timer
deadline=$((SECONDS + 260))
while systemctl is-active --quiet market-maker-prod-nfl-auto.service ||
      systemctl is-active --quiet market-maker-prod-nba-auto.service; do
  if (( SECONDS >= deadline )); then
    echo "An existing trading worker is still active. No update applied." >&2
    exit 2
  fi
  sleep 2
done

if (( dashboard_was )); then systemctl stop market-maker-dashboard.service; fi
runuser -u trader -- git pull --ff-only origin main
runuser -u trader -- .venv/bin/python -m pytest -q \
  tests/test_order_opportunity_audit.py \
  tests/test_account_dashboard.py \
  tests/test_shared_account_risk.py
systemctl daemon-reload
echo "Private Kalshi order audit updated; restoring previous timer states."
