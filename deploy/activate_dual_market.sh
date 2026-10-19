#!/usr/bin/env bash
# Single, owner-authorized NFL + NBA production activation on one Droplet.
# Does not touch the separate funded-account P&L service or Demo trader.
set -Eeuo pipefail
umask 077
[[ $(id -u) -eq 0 ]] || { echo "Root required." >&2; exit 1; }
cd /home/trader/sports-market-maker-prod-auto

nfl=/etc/market-maker-prod-auto.env
nba=/etc/market-maker-prod-nba-auto.env
marker=/etc/market-maker-shared-account.enabled
for f in "$nfl" "$nba" /home/trader/prod-nfl-auto/journal.jsonl /home/trader/prod-nba-auto/journal.jsonl; do
  [[ -f "$f" ]] || { echo "Missing required configuration or journal: $f" >&2; exit 1; }
done
for f in /home/trader/prod-nfl-auto/KILL /home/trader/prod-nba-auto/KILL; do
  [[ ! -e "$f" ]] || { echo "KILL switch exists; refusing activation." >&2; exit 1; }
done

# Stop new scans, then wait for in-flight scans to end. Do not kill an
# order-submitting process or overwrite any trading journal.
systemctl stop market-maker-prod-nfl-auto.timer market-maker-prod-nba-auto.timer
deadline=$((SECONDS + 260))
for unit in market-maker-prod-nfl-auto.service market-maker-prod-nba-auto.service; do
  while systemctl is-active --quiet "$unit"; do
    if (( SECONDS >= deadline )); then
      echo "An existing trading scan is still active. No configuration changed." >&2
      exit 2
    fi
    sleep 2
  done
done

# This is the ONLY executable-code update; both workers are now stopped.
runuser -u trader -- git pull --ff-only origin main
grep -Fq 'fcntl.flock(stream, fcntl.LOCK_EX)' live/production_lock.py || {
  echo "Blocking shared-lock fix missing from checkout." >&2; exit 2;
}
runuser -u trader -- .venv/bin/python -m pytest -q \
  tests/test_production_lock.py \
  tests/test_shared_account_risk.py \
  tests/test_prod_nfl_auto.py \
  tests/test_prod_nba_auto.py

# Signed GET-only account check before any production setting is modified.
systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile="$nfl" \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m tools.dual_account_preflight

# Existing owner production permissions must already be present in both
# protected files. Never replace credentials, limits, or journal histories.
python3 - <<'PY'
from pathlib import Path
required = {
    Path('/etc/market-maker-prod-auto.env'): {
        'KALSHI_ENV':'prod', 'TRADE_MODE':'live',
        'ALLOW_PRODUCTION_TRADING':'YES', 'PROD_AUTO_ARM':'YES'},
    Path('/etc/market-maker-prod-nba-auto.env'): {
        'KALSHI_ENV':'prod', 'TRADE_MODE':'live',
        'ALLOW_PRODUCTION_TRADING':'YES', 'TRADE_MARKET':'nba'},
}
for path, expected in required.items():
    entries = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k, v = line.split('=', 1)
            entries[k.strip()] = v.strip()
    for key, value in expected.items():
        if entries.get(key) != value:
            raise SystemExit(f'Production guard mismatch: {path.name} {key}')
PY

backup=$(mktemp -d /etc/market-maker-dual-backup.XXXXXXXX)
chmod 700 "$backup"
cp -p "$nfl" "$backup/nfl.env"
cp -p "$nba" "$backup/nba.env"
had_marker=0
[[ -e "$marker" ]] && had_marker=1
completed=0
rollback() {
  status=$?
  trap - ERR EXIT
  if (( completed == 0 )); then
    echo "Activation failed: disabling both trading timers and restoring production configuration." >&2
    systemctl stop market-maker-prod-nfl-auto.timer market-maker-prod-nba-auto.timer || true
    cp -p "$backup/nfl.env" "$nfl"
    cp -p "$backup/nba.env" "$nba"
    if (( had_marker == 0 )); then rm -f "$marker"; fi
  fi
  rm -rf "$backup"
  exit "$status"
}
trap rollback ERR

# Replace ONLY the authorization fields; leave keys, other flags,
# original permissions and all financial limits unchanged.
python3 - <<'PY'
from pathlib import Path
overrides = {
    Path('/etc/market-maker-prod-auto.env'): {
        'SMM_DUAL_MARKET': 'YES'},
    Path('/etc/market-maker-prod-nba-auto.env'): {
        'SMM_DUAL_MARKET': 'YES', 'PROD_NBA_AUTO_ARM': 'YES'},
}
for path, values in overrides.items():
    lines = path.read_text().splitlines()
    lines = [line for line in lines
             if line.split('=',1)[0].strip() not in values]
    lines.extend(f'{k}={v}' for k,v in values.items())
    path.write_text('\n'.join(lines) + '\n')
    path.chmod(0o600)
PY
if (( had_marker == 0 )); then
  install -o root -g root -m 0600 /dev/null "$marker"
fi

# Recheck the now dual-enabled exchange account and current NBA inputs.
# A failed source, unsettled foreign order, wrong fee or exhausted budget
# prevents arming the timers.
systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile="$nfl" \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m tools.dual_account_preflight

systemd-run --wait --pipe --collect --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile="$nba" \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m live.prod_nba_auto --preflight --sync-inputs

# The user explicitly authorized both bounded live trading cohorts.
systemctl enable --now market-maker-prod-nfl-auto.timer
systemctl enable --now market-maker-prod-nba-auto.timer
systemctl is-active --quiet market-maker-prod-nfl-auto.timer
systemctl is-active --quiet market-maker-prod-nba-auto.timer

# Force one real scan of each worker to expose any remaining live-mode
# configuration or locking problem immediately, instead of hours later.
# Each worker may submit only permitted post-only orders in its valid window.
systemctl start market-maker-prod-nfl-auto.service
systemctl start market-maker-prod-nba-auto.service

completed=1
trap - ERR
rm -rf "$backup"
echo "DUAL MARKET ACTIVE: both timers and both worker scans succeeded."
echo "The running timers will submit only qualifying, bounded real-money orders."
echo "Signed P&L publishing, Demo, private journals, and risk caps were not reset."
