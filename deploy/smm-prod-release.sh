#!/usr/bin/env bash
# Root-owned, explicit, code-only production release helper.
# Install once outside the git checkout. Do NOT run this automatically on pushes.
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "Root required" >&2; exit 2; }
[[ "$#" == 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Usage: smm-prod-release <40-character approved main commit SHA>" >&2
  exit 2
}
TARGET="$1"
ROOT=/home/trader/sports-market-maker-prod-auto
NFL_TIMER=market-maker-prod-nfl-auto.timer
NBA_TIMER=market-maker-prod-nba-auto.timer
NFL_SVC=market-maker-prod-nfl-auto.service
NBA_SVC=market-maker-prod-nba-auto.service

exec 9>/run/lock/smm-production-release.lock
flock -n 9 || { echo "Another deployment is in progress" >&2; exit 1; }

[[ -d "$ROOT/.git" && -x "$ROOT/.venv/bin/python" ]] || {
  echo "Production checkout or virtualenv missing" >&2; exit 1;
}
[[ "$(runuser -u trader -- git -C "$ROOT" branch --show-current)" == main ]] || {
  echo "Production checkout must be on main" >&2; exit 1;
}
[[ -z "$(runuser -u trader -- git -C "$ROOT" status --porcelain --untracked-files=no)" ]] || {
  echo "Tracked production files have local changes: refusing update" >&2; exit 1;
}

OLD="$(runuser -u trader -- git -C "$ROOT" rev-parse HEAD)"
if [[ "$OLD" == "$TARGET" ]]; then
  echo "PRODUCTION CODE ALREADY AT REQUESTED SHA: $TARGET"
  exit 0
fi

nfl_was=0
nba_was=0
systemctl is-active --quiet "$NFL_TIMER" && nfl_was=1 || true
systemctl is-active --quiet "$NBA_TIMER" && nba_was=1 || true

stopped=0
changed=0
success=0
restore_original_timers() {
  local rc=0
  if (( nfl_was )); then systemctl start "$NFL_TIMER" || rc=1; fi
  if (( nba_was )); then systemctl start "$NBA_TIMER" || rc=1; fi
  return "$rc"
}
on_exit() {
  local rc=$?
  trap - EXIT
  if (( success )); then
    echo "RELEASE VERIFIED: $TARGET"
    exit "$rc"
  fi
  if (( stopped )); then
    if (( changed )); then
      # Do not destroy newly written tracked data to force a rollback.
      if [[ -z "$(runuser -u trader -- git -C "$ROOT" status --porcelain --untracked-files=no)" ]]; then
        if runuser -u trader -- git -C "$ROOT" reset --hard -q "$OLD"; then
          echo "Code rolled back to previous SHA: $OLD" >&2
          changed=0
        fi
      fi
    fi
    if (( changed )); then
      echo "ROLLBACK NOT VERIFIED: funded timers remain stopped for investigation" >&2
    elif restore_original_timers; then
      echo "Original production timer states restored" >&2
    else
      echo "Timer recovery incomplete; inspect funded services before trading" >&2
    fi
  fi
  exit "$((rc == 0 ? 1 : rc))"
}
trap on_exit EXIT

# Avoid mutating the working tree while a funded order pass is executing.
stopped=1
systemctl stop "$NFL_TIMER" "$NBA_TIMER"
deadline=$((SECONDS + 260))
for unit in "$NFL_SVC" "$NBA_SVC"; do
  while :; do
    state="$(systemctl show "$unit" --property=ActiveState --value)"
    case "$state" in
      inactive|failed) break ;;
      active|activating|deactivating|reloading) ;;
      *) echo "Unexpected worker state $unit: $state" >&2; exit 1 ;;
    esac
    (( SECONDS < deadline )) || { echo "Worker did not finish: $unit" >&2; exit 1; }
    sleep 2
  done
done

runuser -u trader -- git -C "$ROOT" fetch --quiet origin main
# Background dry-run logs may append commits to main while CI runs.
# Deploy exactly the tested SHA, not the moving branch head.
if ! runuser -u trader -- git -C "$ROOT" cat-file -e "$TARGET^{commit}" 2>/dev/null; then
  runuser -u trader -- git -C "$ROOT" fetch --quiet origin "$TARGET"
fi
runuser -u trader -- git -C "$ROOT" merge-base --is-ancestor "$TARGET" refs/remotes/origin/main || {
  echo "Requested SHA is not reachable from current main; refusing release" >&2
  exit 1
}
# This is a CODE-ONLY workflow: dependency or systemd unit upgrades require
# a distinct owner-supervised maintenance procedure.
blocked="$(runuser -u trader -- git -C "$ROOT" diff --name-only "$OLD" "$TARGET" -- \
  requirements.txt deploy/market-maker-prod-nba-auto.service \
  deploy/market-maker-prod-nba-auto.timer \
  deploy/market-maker-prod-nfl-auto.service \
  deploy/market-maker-prod-nfl-auto.timer)"
[[ -z "$blocked" ]] || {
  echo "Release changes dependencies or funded systemd units: use manual maintenance." >&2
  exit 1
}
runuser -u trader -- git -C "$ROOT" merge --ff-only "$TARGET"
changed=1

# GitHub CI ran full Python, JS and shell tests for THIS commit.
# The funded micro-Droplet only runs low-memory syntax validation.
runuser -u trader -- "$ROOT/.venv/bin/python" -m compileall -q \
  "$ROOT/live" "$ROOT/kalshi" "$ROOT/markets" "$ROOT/tools"

# Only check a funded account if its timer was originally live.
# Signed production checks use the server's existing protected environment;
# never print environment files or modify arm flags, risk, KILL, or journals.
if (( nfl_was || nba_was )); then
  account_log="$(mktemp /root/smm-account-preflight.XXXXXXXX)"
  chmod 600 "$account_log"
  if ! systemd-run --quiet --wait --pipe --collect --uid=trader \
    -p "WorkingDirectory=$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-auto.env \
    -p Environment=OPENBLAS_NUM_THREADS=1 \
    -p Environment=OMP_NUM_THREADS=1 \
    "$ROOT/.venv/bin/python" -m tools.dual_account_preflight > "$account_log" 2>&1; then
    echo "Funded account GET-only verification failed; details retained at $account_log on Droplet" >&2
    exit 1
  fi
  rm -f "$account_log"
  echo "Funded account GET-only verification: PASS"
fi
if (( nba_was )); then
  nba_log="$(mktemp /root/smm-nba-preflight.XXXXXXXX)"
  chmod 600 "$nba_log"
  if ! systemd-run --quiet --wait --pipe --collect --uid=trader \
    -p "WorkingDirectory=$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
    -p Environment=OPENBLAS_NUM_THREADS=1 \
    -p Environment=OMP_NUM_THREADS=1 \
    "$ROOT/.venv/bin/python" -m live.prod_nba_auto --preflight --sync-inputs > "$nba_log" 2>&1; then
    echo "NBA GET-only verification failed; details retained at $nba_log on Droplet" >&2
    exit 1
  fi
  rm -f "$nba_log"
  echo "NBA GET-only verification: PASS"
fi

# Code-only: NEVER alter the installed systemd units here, and NEVER
# start an originally inactive production timer or force a worker pass.
if ! restore_original_timers; then
  echo "Timer restore failed after validation; manual inspection required" >&2
  exit 1
fi
success=1
printf 'DEPLOYED_SHA=%s\n' "$TARGET"
printf 'PRESERVED_TIMER_STATES NFL=%s NBA=%s\n' "$nfl_was" "$nba_was"
