#!/usr/bin/env bash
# Owner-run deployment. Does not arm a stopped trader or change dollar limits.
set -Eeuo pipefail
if [[ "$(id -u)" != "0" ]]; then
  echo "Run with sudo."
  exit 1
fi
CHECKOUT=/home/trader/sports-market-maker-prod-auto
TIMER=market-maker-prod-nfl-auto.timer
DASHBOARD=market-maker-dashboard.service
WAS_ACTIVE=0
DASHBOARD_WAS_ACTIVE=0
systemctl is-active --quiet "$TIMER" && WAS_ACTIVE=1
systemctl is-active --quiet "$DASHBOARD" && DASHBOARD_WAS_ACTIVE=1
restore_timer() {
  if [[ "$DASHBOARD_WAS_ACTIVE" == "1" ]]; then
    systemctl start "$DASHBOARD" || echo "Account dashboard restart failed; inspect its service log."
  fi
  if [[ "$WAS_ACTIVE" == "1" ]]; then systemctl start "$TIMER"; fi
}
trap restore_timer EXIT
systemctl stop "$TIMER"
# Free the old dashboard's analysis imports while waiting for the worker.
# This read-only service can be restarted without touching exchange orders.
if [[ "$DASHBOARD_WAS_ACTIVE" == "1" ]]; then systemctl stop "$DASHBOARD"; fi
worker_busy() {
  local state
  state=$(systemctl show -p ActiveState --value market-maker-prod-nfl-auto.service)
  [[ "$state" == "active" || "$state" == "activating" || "$state" == "deactivating" || "$state" == "reloading" ]]
}
# Let an in-flight order finish and write its receipt. Never kill a submitting worker.
for _ in $(seq 1 60); do
  if ! worker_busy; then break; fi
  sleep 5
done
if worker_busy; then
  echo "Worker still running. Update stopped safely; try again after it finishes."
  exit 1
fi
sudo -u trader git -C "$CHECKOUT" pull --ff-only origin main
test -x "$CHECKOUT/.venv/bin/python"
install -m 644 "$CHECKOUT/deploy/market-maker-dashboard.service" /etc/systemd/system/
install -m 644 "$CHECKOUT/deploy/market-maker-prod-nfl-auto.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable market-maker-dashboard.service
systemctl restart market-maker-dashboard.service
systemctl is-active --quiet market-maker-dashboard.service
echo "Updated. Private account dashboard listens on server 127.0.0.1:8765."
echo "Existing NFL timer state is preserved; dollar limits are unchanged."
echo "Memory now:"
free -h
echo "Recent worker result (may describe the run before this update):"
systemctl show market-maker-prod-nfl-auto.service -p Result -p MemoryPeak -p MemoryMax
echo "From your own computer: ssh -N -L 8765:127.0.0.1:8765 YOUR_SSH_LOGIN"
echo "Then open http://127.0.0.1:8765 in your browser."
