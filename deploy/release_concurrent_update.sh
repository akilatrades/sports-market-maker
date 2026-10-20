#!/usr/bin/env bash
# One-step safe release for already authorized concurrent NFL/NBA live workers.
# No changes to arm flags, risk caps, secrets, journals, or Kalshi orders.
set -Eeuo pipefail
umask 077
[[ $(id -u) -eq 0 ]] || { echo "Root required." >&2; exit 1; }
ROOT=/home/trader/sports-market-maker-prod-auto
NFL_TIMER=market-maker-prod-nfl-auto.timer
NBA_TIMER=market-maker-prod-nba-auto.timer
DASHBOARD=market-maker-dashboard.service
cd "$ROOT"

nfl_was=0
nba_was=0
dashboard_was=0
updated=0
validated=0
finished=0
systemctl is-active --quiet "$NFL_TIMER" && nfl_was=1
systemctl is-active --quiet "$NBA_TIMER" && nba_was=1
systemctl is-active --quiet "$DASHBOARD" && dashboard_was=1

on_exit() {
  local status=$?
  trap - EXIT
  if (( updated && ! validated )); then
    echo "RELEASE NOT VERIFIED: live timers remain stopped to protect the account." >&2
    if (( dashboard_was )); then
      systemctl restart "$DASHBOARD" || echo "Private dashboard restart unavailable." >&2
    fi
    exit "$status"
  fi
  if (( dashboard_was )); then systemctl restart "$DASHBOARD" || status=3; fi
  if (( nfl_was )); then systemctl start "$NFL_TIMER" || status=3; fi
  if (( nba_was )); then systemctl start "$NBA_TIMER" || status=3; fi
  if (( status != 0 )); then
    echo "RELEASE INCOMPLETE: a previous service could not be restored." >&2
    exit "$status"
  fi
  if (( finished )); then
    echo "RELEASE VERIFIED: tests and signed preflights passed; old timers restored."
    echo "No exchange POSTs were made by the release script."
    runuser -u trader -- .venv/bin/python -m tools.production_status || true
  fi
}
trap on_exit EXIT

systemctl stop "$NFL_TIMER" "$NBA_TIMER"
deadline=$((SECONDS + 260))
for unit in market-maker-prod-nfl-auto.service market-maker-prod-nba-auto.service; do
  while :; do
    state=$(systemctl show "$unit" --property=ActiveState --value)
    case "$state" in
      inactive|failed) break ;;
      active|activating|deactivating|reloading) ;;
      *) echo "Unknown worker state; refusing update." >&2; exit 2 ;;
    esac
    if (( SECONDS >= deadline )); then
      echo "A worker is still active; refusing update." >&2
      exit 2
    fi
    sleep 2
  done
done

runuser -u trader -- git pull --ff-only origin main
updated=1
runuser -u trader -- .venv/bin/python -m pytest -q \
  tests/test_nfl_inputs.py \
  tests/test_nfl_projection_week.py \
  tests/test_execution_scorecard.py \
  tests/test_nfl_memory.py \
  tests/test_production_status_health.py \
  tests/test_order_opportunity_audit.py \
  tests/test_account_dashboard.py \
  tests/test_shared_account_risk.py \
  tests/test_prod_nfl_auto.py \
  tests/test_prod_nba_auto.py \
  tests/test_production_lock.py
node tests/account_dashboard.cjs

systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory="$ROOT" \
  -p EnvironmentFile=/etc/market-maker-prod-auto.env \
  "$ROOT/.venv/bin/python" -m tools.dual_account_preflight

# NFL source synchronization is public GET only and updates no executable code.
runuser -u trader -- .venv/bin/python -m live.nfl_inputs

systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory="$ROOT" \
  -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  "$ROOT/.venv/bin/python" -m live.prod_nba_auto --preflight --sync-inputs

validated=1
finished=1
