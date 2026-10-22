#!/usr/bin/env bash
# Owner controls for the spread maker pilot (deploy/PROD_SPREAD_AUTO.md).
# Run as root in the DigitalOcean console:
#   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh [command]
#
#   (no command)  install the timer from GitHub main and start SHADOW mode
#                 (public data only; no orders, no credentials used)
#   --preflight   signed GET-only readiness check; places nothing
#   --arm         allow real orders (pilot caps); runs --preflight first
#   --disarm      no new orders; resting quotes expire within 65 minutes
#   --cancel      cancel this bot's resting orders now and keep it halted
#   --resume      remove the halt left by --cancel (does not arm)
#   --reconcile   after an "Ambiguous spread order" halt: signed GET-only
#                 lookup that records the order as placed or never placed
#   --off         disarm, cancel, and stop the timer (shadow stops too)
#   --status      timer, arm and halt state, and both ledgers' summaries
#
# Never touches the NBA or NFL bots, their timers, journals or limits, and
# never prints the contents of any settings file.
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "Run with sudo" >&2; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
STATE=/home/trader/prod-spread-auto
UNIT=market-maker-prod-spread-auto
ACCOUNT_ENV=/etc/market-maker-prod-nba-auto.env
ARM_ENV=/etc/market-maker-spread.env
ARM_MARKER=/etc/market-maker-spread.enabled
SHARED_MARKER=/etc/market-maker-shared-account.enabled
COMMAND="${1:-}"
tgit() { runuser -u trader -- git -C "$ROOT" "$@"; }
as_trader() {
  systemd-run --quiet --wait --pipe --collect --uid=trader \
    -p "WorkingDirectory=$ROOT" -p "EnvironmentFile=$ACCOUNT_ENV" \
    -p Environment=OPENBLAS_NUM_THREADS=1 -p Environment=OMP_NUM_THREADS=1 \
    "$ROOT/.venv/bin/python" -m live.prod_spread_auto "$@"
}
set_arm() {
  install -m 600 -o root -g root /dev/null "$ARM_ENV.tmp"
  printf 'SPREAD_AUTO_ARM=%s\n' "$1" > "$ARM_ENV.tmp"
  mv -f "$ARM_ENV.tmp" "$ARM_ENV"
}
disarm() {
  rm -f "$ARM_MARKER"
  set_arm NO
  echo "Disarmed: no new spread orders. Resting quotes expire within 65 minutes"
  echo "(use --cancel to pull them now). Shadow mode keeps running."
}
cancel_now() {
  if [[ ! -f "$STATE/journal.jsonl" ]]; then
    echo "The spread maker has never traded: nothing to cancel."
    return 0
  fi
  runuser -u trader -- touch "$STATE/KILL"
  echo "KILL is in place: every pass cancels this bot's orders and places none."
  if ! flock -n /run/lock/smm-production-release.lock true; then
    echo "A code release is running, so the cancel pass waits for the next"
    echo "timer pass (within 10 minutes). Run --cancel again after the release"
    echo "to cancel at once."
  else
    systemctl start "$UNIT.service" || true
    journalctl -u "$UNIT.service" -n 5 --no-pager -o cat | grep -E "KILL|HALT|Error" || true
  fi
  echo "Run --resume to remove it."
}
yesno() { [[ -e "$1" ]] && echo yes || echo no; }

case "$COMMAND" in
  --status)
    echo "Timer active: $(systemctl is-active "$UNIT.timer" 2>/dev/null || true)"
    echo "Arm marker: $(yesno "$ARM_MARKER")"
    grep -qx 'SPREAD_AUTO_ARM=YES' "$ARM_ENV" 2>/dev/null && echo "Arm switch: YES" || echo "Arm switch: no"
    echo "KILL (halted): $(yesno "$STATE/KILL")"
    runuser -u trader -- bash -c "cd '$ROOT' && .venv/bin/python -m live.prod_spread_auto --status"
    exit 0 ;;
  --disarm) disarm; exit 0 ;;
  --cancel) cancel_now; exit 0 ;;
  --resume)
    runuser -u trader -- rm -f "$STATE/KILL"
    echo "KILL removed. The bot trades again only if it is armed ($(yesno "$ARM_MARKER"))."
    exit 0 ;;
  --off)
    disarm
    cancel_now
    systemctl disable --now "$UNIT.timer"
    echo "Spread maker is OFF (timer stopped)."
    exit 0 ;;
  --preflight)
    as_trader --preflight
    exit 0 ;;
  --reconcile)
    as_trader --reconcile
    echo "If bots_can_trade is false and it says too recent, run this again in"
    echo "10 minutes. Anything else: stop and ask before trading again."
    exit 0 ;;
  --arm)
    systemctl is-active --quiet "$UNIT.timer" || {
      echo "Run this script without a command first (installs the timer)." >&2; exit 1; }
    [[ -e "$SHARED_MARKER" ]] || { echo "Shared-account mode is not enabled; refusing." >&2; exit 1; }
    [[ ! -e "$STATE/KILL" ]] || { echo "KILL is in place; run --resume first." >&2; exit 1; }
    for setting in KALSHI_ENV=prod ALLOW_PRODUCTION_TRADING=YES SMM_DUAL_MARKET=YES; do
      grep -qx "$setting" "$ACCOUNT_ENV" || {
        echo "The NBA settings file does not have ${setting%%=*} set as expected; refusing." >&2
        exit 1; }
    done
    echo "Running the GET-only preflight..."
    as_trader --preflight || { echo "Preflight failed: NOT armed." >&2; exit 1; }
    set_arm YES
    install -m 644 -o root -g root /dev/null "$ARM_MARKER"
    echo "ARMED. The next pass (within 10 minutes) may place real one-contract quotes."
    echo "Caps: \$25 open, \$5 daily and \$15 total own loss stops, inside the shared"
    echo "account stops. Undo: --disarm (no new orders) or --cancel (pull them now)."
    exit 0 ;;
  "") ;;
  *) echo "Unknown command: $COMMAND" >&2; exit 2 ;;
esac

# Install: never while a code release is changing the checkout.
exec 9>/run/lock/smm-production-release.lock
flock -n 9 || { echo "A code release is running; try again in a few minutes." >&2; exit 1; }
case "$(tgit remote get-url origin)" in
  https://github.com/akilatrades/sports-market-maker|https://github.com/akilatrades/sports-market-maker.git) ;;
  *) echo "The checkout's origin is not the project repository; refusing." >&2; exit 1 ;;
esac
[[ -z "$(tgit status --porcelain --untracked-files=no)" ]] || {
  echo "The server checkout has local changes; refusing. Deploy cleanly first." >&2; exit 1; }
[[ -f "$ROOT/live/prod_spread_auto.py" ]] || {
  echo "Deploy the code first (Deploy funded worker code -> DEPLOY_CODE)." >&2; exit 1; }
tgit fetch --quiet origin main
for f in "$UNIT.service" "$UNIT.timer"; do
  tgit cat-file -e "FETCH_HEAD:deploy/$f" 2>/dev/null || {
    echo "deploy/$f is not on GitHub main yet: merge the pull request first." >&2; exit 1; }
  tgit show "FETCH_HEAD:deploy/$f" > "/etc/systemd/system/$f"
  chown root:root "/etc/systemd/system/$f"
  chmod 644 "/etc/systemd/system/$f"
done
[[ -f "$ARM_ENV" ]] || set_arm NO
systemctl daemon-reload
flock -u 9
echo "Units installed from GitHub main $(tgit rev-parse --short FETCH_HEAD); server code at $(tgit rev-parse --short HEAD)."
echo "Running one shadow pass now..."
if systemctl start "$UNIT.service"; then
  systemctl enable --now "$UNIT.timer"
  journalctl -u "$UNIT.service" -n 1 --no-pager -o cat | cut -c1-300 || true
  echo "OK: SHADOW mode every 10 minutes (no orders). Arm with --arm when ready."
else
  journalctl -u "$UNIT.service" -n 5 --no-pager -o cat | cut -c1-300 || true
  echo "The shadow pass failed (reason above). The timer was NOT turned on." >&2
  exit 1
fi
