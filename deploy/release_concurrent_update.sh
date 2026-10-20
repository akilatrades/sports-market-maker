#!/usr/bin/env bash
# One-step safe release for already authorized concurrent NFL/NBA live workers.
# No changes to arm flags, risk caps, secrets, journals, or Kalshi orders.
# Host is a small funded-account Droplet: full test matrix already runs in
# GitHub Actions. Running the large pytest suite here can trigger Linux OOM.
# Explicit --resume-nba handles a previously interrupted deployment that left
# an originally active NBA timer stopped. Never resurrect NFL by inference.
set -Eeuo pipefail
umask 077
[[ $(id -u) -eq 0 ]] || { echo "Root required." >&2; exit 1; }
resume_nba=0
case "${1:-}" in
  "") ;;
  --resume-nba) resume_nba=1 ;;
  *) echo "Usage: bash deploy/release_concurrent_update.sh [--resume-nba]" >&2; exit 2 ;;
esac
[[ $# -le 1 ]] || { echo "Too many release arguments." >&2; exit 2; }
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
if (( resume_nba )); then
  # The user explicitly asked to restore NBA following a failed guarded
  # release. Do this ONLY after signed exchange preflights pass below.
  nba_was=1
  echo "NBA timer recovery requested; will start only after verification."
fi

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
# CI already ran pytest for Python 3.11 + 3.12, JS and shell syntax.
# DO NOT rerun heavy model imports / pytest on the funded micro-Droplet.
# Standard-library py_compile catches checkout corruption/syntax cheaply.
echo "Checking release Python syntax (low-memory; full tests passed in CI)."
runuser -u trader -- .venv/bin/python -m compileall -q live kalshi markets tools

# Preflight uses signed Kalshi GETs, with lower native-thread memory overhead.
# Never submit or cancel anything from this release script.
echo "Checking real exchange account and both cohort budgets (GET only)."
systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory="$ROOT" \
  -p EnvironmentFile=/etc/market-maker-prod-auto.env \
  -p Environment=OPENBLAS_NUM_THREADS=1 \
  -p Environment=OMP_NUM_THREADS=1 \
  -p Environment=MALLOC_ARENA_MAX=2 \
  "$ROOT/.venv/bin/python" -m tools.dual_account_preflight

# Only refresh NFL model if it was previously live; NBA-only recovery must
# not pay the memory or network costs of a disabled NFL cohort.
if (( nfl_was )); then
  runuser -u trader -- env OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MALLOC_ARENA_MAX=2 \
    .venv/bin/python -m live.nfl_inputs
fi

echo "Checking NBA model, current injury/odds feeds and signed account (GET only)."
systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory="$ROOT" \
  -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  -p Environment=OPENBLAS_NUM_THREADS=1 \
  -p Environment=OMP_NUM_THREADS=1 \
  -p Environment=MALLOC_ARENA_MAX=2 \
  "$ROOT/.venv/bin/python" -m live.prod_nba_auto --preflight --sync-inputs

# A git pull alone does NOT update installed systemd timers; activate only
# after all of the above validated, while both trade timers remain stopped.
install -o root -g root -m 0644 "deploy/$NBA_TIMER" "/etc/systemd/system/$NBA_TIMER"
systemctl daemon-reload
validated=1
finished=1
