#!/bin/bash
# Root-owned Go live / Stop control for the funded NBA + NFL workers.
#
# Installed once by the owner from a pinned commit
# (deploy/install_github_control_helper.sh); GitHub Actions may then call it
# through `sudo -n /usr/local/sbin/smm-prod-control <verb>`.
#
# PUBLIC OUTPUT RULE: GitHub Actions logs for this repository are public.
# This helper prints ONLY step names, PASS/FAIL, timer on/off states and the
# deployed commit. It never prints environment files, keys, hostnames,
# balances, positions, tickers or order IDs. Every account-reading check
# writes its full output to a root-only file under /root/smm-control-logs.
#
# ROOT-SAFETY RULES: run from /, with a fixed PATH and isolated Python, so
# nothing the trader account controls (its home directory, the checkout,
# the virtualenv, the state directories) is ever imported, executed,
# followed or written by root. Repository code runs only as trader.
#
# Verbs:
#   status                 read-only summary
#   go-live <main SHA>     verify code + account, arm both bots, enable timers
#   stop                   no new orders: stop and disable both timers
#   stop-and-cancel        stop, then cancel the bots' own resting orders
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "ERROR: root required" >&2; exit 2; }
cd /
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP BASH_ENV ENV
MAIN_PID=$$

ROOT=/home/trader/sports-market-maker-prod-auto
PY="$ROOT/.venv/bin/python"
NFL_ENV=/etc/market-maker-prod-auto.env
NBA_ENV=/etc/market-maker-prod-nba-auto.env
MARKER=/etc/market-maker-shared-account.enabled
NFL_DIR=/home/trader/prod-nfl-auto
NBA_DIR=/home/trader/prod-nba-auto
NFL_TIMER=market-maker-prod-nfl-auto.timer
NBA_TIMER=market-maker-prod-nba-auto.timer
NFL_SVC=market-maker-prod-nfl-auto.service
NBA_SVC=market-maker-prod-nba-auto.service
LOGDIR=/root/smm-control-logs
KILL_TAG="created-by-smm-prod-control"
# Executable code that must match the requested commit before going live.
CODE_PATHS=(live kalshi markets tools requirements.txt)

usage() {
  echo "Usage: smm-prod-control status | go-live <40-char main SHA> | stop | stop-and-cancel" >&2
  exit 2
}

say() { printf '%s\n' "$*"; }

state_of() { systemctl is-active "$1" 2>/dev/null || true; }

as_trader() { runuser -u trader -- "$@"; }

tgit() { as_trader git -C "$ROOT" "$@" 2>/dev/null; }

flag_is() {
  # flag_is <file> <KEY> <VALUE>: compare without ever printing the file.
  python3 -I - "$1" "$2" "$3" <<'PY'
import sys
path, key, want = sys.argv[1:]
entries = {}
for line in open(path, encoding="utf-8").read().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        entries[k.strip()] = v.strip()
sys.exit(0 if entries.get(key) == want else 1)
PY
}

yes_no() { if "$@"; then echo yes; else echo no; fi; }

kill_present() { [[ -e "$1/KILL" || -L "$1/KILL" ]]; }

take_lock() {
  # Same lock as the code-release helper: never deploy and arm at once.
  # Stopping waits up to five minutes for a running deploy or go-live.
  exec 9>/run/lock/smm-production-release.lock
  flock -w "$1" 9 || { say "ERROR: another deployment or control action is running"; exit 1; }
}

wait_idle() {
  local deadline=$((SECONDS + 260)) unit state
  for unit in "$NFL_SVC" "$NBA_SVC"; do
    while :; do
      state="$(systemctl show "$unit" --property=ActiveState --value 2>/dev/null || true)"
      case "$state" in
        inactive|failed) break ;;
        active|activating|deactivating|reloading) ;;
        *) say "ERROR: unexpected worker state"; return 1 ;;
      esac
      (( SECONDS < deadline )) || { say "ERROR: a worker scan did not finish in time"; return 1; }
      sleep 2
    done
  done
}

stop_timers() {
  # Stop each unit on its own so one failure cannot block the other, then
  # verify: a stop that did not take effect is an error, never a success.
  local unit ok=1
  for unit in "$NFL_TIMER" "$NBA_TIMER"; do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
    systemctl stop "$unit" >/dev/null 2>&1 || true
  done
  for unit in "$NFL_TIMER" "$NBA_TIMER"; do
    if systemctl is-active --quiet "$unit" || systemctl is-enabled --quiet "$unit" 2>/dev/null; then
      say "ERROR: $unit is still on after stopping"
      ok=0
    fi
  done
  (( ok )) || return 1
  wait_idle
}

new_log() {
  mkdir -p "$LOGDIR"
  chmod 700 "$LOGDIR"
  local file
  file="$(mktemp "$LOGDIR/$1.$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")"
  chmod 600 "$file"
  # Keep the 60 most recent logs.
  find "$LOGDIR" -maxdepth 1 -type f -printf '%T@ %p\n' | sort -rn | tail -n +61 \
    | cut -d' ' -f2- | xargs -r rm -f
  printf '%s' "$file"
}

run_check() {
  # run_check <name> <env file> <python args...>; full output stays on the Droplet.
  local name="$1" envfile="$2" log
  shift 2
  log="$(new_log "$name")"
  if systemd-run --quiet --wait --pipe --collect --uid=trader \
      -p "WorkingDirectory=$ROOT" \
      -p "EnvironmentFile=$envfile" \
      -p Environment=OPENBLAS_NUM_THREADS=1 \
      -p Environment=OMP_NUM_THREADS=1 \
      "$PY" "$@" >"$log" 2>&1; then
    say "CHECK $name: PASS"
  else
    say "CHECK $name: FAIL (details kept on the Droplet in $LOGDIR)"
    return 1
  fi
}

print_status() {
  local sha
  sha="$(tgit rev-parse HEAD || echo unknown)"
  say "DEPLOYED_SHA=$sha"
  say "NBA_TIMER=$(state_of "$NBA_TIMER")"
  say "NFL_TIMER=$(state_of "$NFL_TIMER")"
  say "NBA_TIMER_ENABLED_AT_BOOT=$(systemctl is-enabled "$NBA_TIMER" 2>/dev/null || true)"
  say "NFL_TIMER_ENABLED_AT_BOOT=$(systemctl is-enabled "$NFL_TIMER" 2>/dev/null || true)"
  say "NBA_LAST_SCAN_RESULT=$(systemctl show "$NBA_SVC" -p Result --value 2>/dev/null || true)"
  say "NFL_LAST_SCAN_RESULT=$(systemctl show "$NFL_SVC" -p Result --value 2>/dev/null || true)"
  say "NBA_KILL_SWITCH=$(kill_present "$NBA_DIR" && echo present || echo absent)"
  say "NFL_KILL_SWITCH=$(kill_present "$NFL_DIR" && echo present || echo absent)"
  say "SHARED_ACCOUNT_MARKER=$( [[ -e "$MARKER" ]] && echo present || echo absent )"
  if [[ -f "$NBA_ENV" ]]; then
    say "NBA_ARM_FLAG=$(yes_no flag_is "$NBA_ENV" PROD_NBA_AUTO_ARM YES)"
  fi
  if [[ -f "$NFL_ENV" ]]; then
    say "NFL_ARM_FLAG=$(yes_no flag_is "$NFL_ENV" PROD_AUTO_ARM YES)"
  fi
}

# --- go-live -----------------------------------------------------------------

BACKUP=""
HAD_MARKER=0
COMPLETED=0
ARMING=0

restore_file() {
  # restore_file <backup> <target>: atomic, keeps the original owner and mode.
  local tmp="$2.smm-restore"
  cp -p "$1" "$tmp" && mv -f "$tmp" "$2"
}

on_go_live_failure() {
  local rc=$?
  # Traps also fire inside $(...) subshells under set -E; act only in the
  # main shell so a rollback never runs twice or prints into a capture.
  (( BASHPID == MAIN_PID )) || exit 1
  trap - ERR EXIT
  set +e
  if (( COMPLETED == 0 )); then
    local unit
    for unit in "$NFL_TIMER" "$NBA_TIMER"; do
      systemctl disable --now "$unit" >/dev/null 2>&1
    done
    if (( ARMING )); then
      local restored=1
      restore_file "$BACKUP/nfl.env" "$NFL_ENV" || restored=0
      restore_file "$BACKUP/nba.env" "$NBA_ENV" || restored=0
      (( HAD_MARKER )) || rm -f "$MARKER"
      rm -f "$NFL_ENV.smm-tmp" "$NBA_ENV.smm-tmp"
      if (( restored )); then
        say "GO_LIVE FAILED: settings restored and both bots left OFF"
      else
        say "GO_LIVE FAILED: both bots OFF, but the settings restore needs a console check"
      fi
    else
      say "GO_LIVE FAILED before arming: settings unchanged, both bots left OFF"
    fi
  fi
  [[ -n "$BACKUP" ]] && rm -rf "$BACKUP"
  exit "$(( rc == 0 ? 1 : rc ))"
}

go_live() {
  local target="$1"
  [[ "$target" =~ ^[0-9a-f]{40}$ ]] || usage
  take_lock 0

  say "STEP prerequisites"
  [[ -d "$ROOT/.git" && -x "$PY" ]] || { say "ERROR: production checkout or virtualenv missing"; exit 1; }
  for f in "$NFL_ENV" "$NBA_ENV" "$NFL_DIR/journal.jsonl" "$NBA_DIR/journal.jsonl"; do
    [[ -f "$f" ]] || { say "ERROR: a required settings file or journal is missing"; exit 1; }
  done
  for d in "$NFL_DIR" "$NBA_DIR"; do
    ! kill_present "$d" || { say "ERROR: a KILL switch is present; remove it deliberately before going live"; exit 1; }
  done
  [[ "$(tgit branch --show-current)" == main ]] || { say "ERROR: production checkout is not on main"; exit 1; }
  [[ -z "$(tgit status --porcelain --untracked-files=no)" ]] || {
    say "ERROR: production checkout has local changes"; exit 1; }
  [[ -z "$(tgit status --porcelain --untracked-files=all -- "${CODE_PATHS[@]}")" ]] || {
    say "ERROR: production checkout has untracked files in trading code"; exit 1; }

  say "STEP code matches the requested commit"
  tgit fetch --quiet origin main || { say "ERROR: could not fetch main on the Droplet"; exit 1; }
  if ! tgit cat-file -e "$target^{commit}"; then
    tgit fetch --quiet origin "$target" || true
  fi
  tgit merge-base --is-ancestor "$target" refs/remotes/origin/main || {
    say "ERROR: requested commit is not on main"; exit 1; }
  if ! tgit diff --quiet HEAD "$target" -- "${CODE_PATHS[@]}"; then
    say "ERROR: deployed trading code differs from the requested commit."
    say "Run 'Deploy funded worker code' with DEPLOY_CODE first, then Go live again."
    exit 1
  fi
  say "DEPLOYED_SHA=$(tgit rev-parse HEAD)"

  say "STEP owner production settings already present"
  local ok=1 kv
  for kv in KALSHI_ENV=prod TRADE_MODE=live ALLOW_PRODUCTION_TRADING=YES PROD_AUTO_ARM=YES; do
    flag_is "$NFL_ENV" "${kv%%=*}" "${kv#*=}" || { say "ERROR: NFL settings: ${kv%%=*} missing or different"; ok=0; }
  done
  for kv in KALSHI_ENV=prod TRADE_MODE=live ALLOW_PRODUCTION_TRADING=YES TRADE_MARKET=nba; do
    flag_is "$NBA_ENV" "${kv%%=*}" "${kv#*=}" || { say "ERROR: NBA settings: ${kv%%=*} missing or different"; ok=0; }
  done
  (( ok )) || exit 1

  trap on_go_live_failure ERR EXIT
  say "STEP pause both bots while checking"
  stop_timers

  say "STEP signed read-only account check (before arming)"
  run_check account-before "$NFL_ENV" -m tools.dual_account_preflight

  BACKUP="$(mktemp -d /root/smm-control-backup.XXXXXXXX)"
  chmod 700 "$BACKUP"
  cp -p "$NFL_ENV" "$BACKUP/nfl.env"
  cp -p "$NBA_ENV" "$BACKUP/nba.env"
  if [[ -e "$MARKER" ]]; then HAD_MARKER=1; fi
  ARMING=1

  say "STEP arm both bots for shared-account trading"
  python3 -I - "$NFL_ENV" "$NBA_ENV" <<'PY'
import os
import sys
from pathlib import Path

nfl, nba = map(Path, sys.argv[1:])
overrides = {
    nfl: {"SMM_DUAL_MARKET": "YES"},
    nba: {"SMM_DUAL_MARKET": "YES", "PROD_NBA_AUTO_ARM": "YES"},
}
for path, values in overrides.items():
    lines = [
        line
        for line in path.read_text().splitlines()
        if line.split("=", 1)[0].strip() not in values
    ]
    lines.extend(f"{k}={v}" for k, v in values.items())
    st = path.stat()
    tmp = path.with_name(path.name + ".smm-tmp")
    try:
        tmp.write_text("\n".join(lines) + "\n")
        os.chown(tmp, st.st_uid, st.st_gid)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
PY
  if [[ ! -e "$MARKER" ]]; then install -o root -g root -m 0600 /dev/null "$MARKER"; fi

  say "STEP signed read-only checks (after arming)"
  run_check account-after "$NFL_ENV" -m tools.dual_account_preflight
  run_check nba-readiness "$NBA_ENV" -m live.prod_nba_auto --preflight --sync-inputs

  say "STEP enable both timers"
  systemctl enable --now "$NFL_TIMER" >/dev/null 2>&1
  systemctl enable --now "$NBA_TIMER" >/dev/null 2>&1
  systemctl is-active --quiet "$NFL_TIMER"
  systemctl is-active --quiet "$NBA_TIMER"
  COMPLETED=1
  trap - ERR EXIT
  rm -rf "$BACKUP"
  say "LIVE: NBA_TIMER=$(state_of "$NBA_TIMER") NFL_TIMER=$(state_of "$NFL_TIMER")"
  say "Bots will post only qualifying, capped, post-only NO orders in their entry windows."
}

# --- stop --------------------------------------------------------------------

stop_only() {
  take_lock 300
  say "STEP stop and disable both timers"
  stop_timers
  say "STOPPED: NBA_TIMER=$(state_of "$NBA_TIMER") NFL_TIMER=$(state_of "$NFL_TIMER")"
  say "No new orders. Orders already resting were NOT cancelled; they expire at tip-off."
}

stop_and_cancel() {
  take_lock 300
  say "STEP stop and disable both timers"
  stop_timers
  local d svc name content failed=0
  for d in "$NBA_DIR" "$NFL_DIR"; do
    if [[ -L "$d/KILL" ]]; then
      # A linked KILL could look absent to the worker, which would then
      # trade instead of cancel. Refuse rather than run a normal pass.
      say "ERROR: a KILL switch is a link; fix it from the console. Bots are stopped."
      exit 1
    fi
    if [[ ! -e "$d/KILL" ]]; then
      # Written by trader, never root: root must not write inside a
      # trader-owned directory. noclobber refuses any existing path.
      as_trader bash -c 'set -o noclobber; umask 077; printf "%s\n" "$1" > "$2"' \
        _ "$KILL_TAG" "$d/KILL" 2>/dev/null || true
    fi
    if ! as_trader test -f "$d/KILL" || [[ -L "$d/KILL" ]]; then
      say "ERROR: could not place a KILL switch; no cancel pass was run. Bots are stopped."
      exit 1
    fi
  done
  for svc in "$NBA_SVC" "$NFL_SVC"; do
    name="${svc#market-maker-prod-}"
    name="${name%-auto.service}"
    say "STEP cancel ${name^^} resting orders"
    if systemctl start "$svc" >/dev/null 2>&1 \
        && [[ "$(systemctl show "$svc" -p Result --value 2>/dev/null)" == success ]]; then
      say "CANCEL ${name^^}: PASS"
    else
      say "CANCEL ${name^^}: FAIL (details in the Droplet journal: journalctl -u $svc)"
      failed=1
    fi
  done
  if (( failed )); then
    say "KILL switches left in place. Check Kalshi for any remaining resting orders."
    exit 1
  fi
  for d in "$NBA_DIR" "$NFL_DIR"; do
    # Remove only switches this helper created; an owner's own KILL stays.
    # Read as trader with a timeout so a planted FIFO cannot hang root.
    content="$(timeout 5 runuser -u trader -- head -c 64 "$d/KILL" 2>/dev/null || true)"
    if [[ ! -L "$d/KILL" && "$content" == "$KILL_TAG" ]]; then
      rm -f "$d/KILL"
    fi
  done
  say "STOPPED AND CANCELLED: NBA_TIMER=$(state_of "$NBA_TIMER") NFL_TIMER=$(state_of "$NFL_TIMER")"
}

case "${1:-}" in
  status) [[ "$#" == 1 ]] || usage; print_status ;;
  go-live) [[ "$#" == 2 ]] || usage; go_live "$2"; print_status ;;
  stop) [[ "$#" == 1 ]] || usage; stop_only; print_status ;;
  stop-and-cancel) [[ "$#" == 1 ]] || usage; stop_and_cancel; print_status ;;
  *) usage ;;
esac
