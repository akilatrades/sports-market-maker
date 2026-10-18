#!/usr/bin/env bash
# Owner-run handoff. Refuses new NBA risk unless production preflight passes.
set -euo pipefail
cd /home/trader/sports-market-maker-prod-auto
[[ $(id -u) == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ -f /etc/market-maker-prod-nba-auto.env ]] || { echo 'Run staging first.' >&2; exit 1; }
if systemctl is-active --quiet market-maker-prod-nba-auto.timer || systemctl is-active --quiet market-maker-prod-nba-auto.service; then
  echo 'NBA timer is already active; inspect its status before another handoff.' >&2
  exit 1
fi
nfl_was_active=0
systemctl is-active --quiet market-maker-prod-nfl-auto.timer && nfl_was_active=1
restore_nfl() {
  if [[ $nfl_was_active == 1 ]]; then
    systemctl start market-maker-prod-nfl-auto.timer
    echo 'NBA handoff failed; restored the previously active NFL timer.' >&2
  fi
}
trap restore_nfl ERR
systemctl stop market-maker-prod-nfl-auto.timer
deadline=$((SECONDS + 260))
while systemctl is-active --quiet market-maker-prod-nfl-auto.service; do
  if (( SECONDS >= deadline )); then
    echo 'NFL worker did not finish; handoff aborted.' >&2
    false
  fi
  sleep 2
done
systemd-run --wait --pipe --collect --uid=trader \
  --property=WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  --property=EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m live.prod_nba_auto --preflight --sync-inputs
# The checks above do not write exchange orders, cancel NFL positions, clear
# journals, or reset KILL. Owner invocation of this script performs activation.
trap - ERR
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/market-maker-prod-nba-auto.env')
lines = [line for line in p.read_text().splitlines() if line.split('=',1)[0].strip() != 'PROD_NBA_AUTO_ARM']
p.write_text('\n'.join(lines + ['PROD_NBA_AUTO_ARM=YES']) + '\n')
PY
if ! systemctl enable --now market-maker-prod-nba-auto.timer; then
  echo 'NBA activation needs inspection. NFL remains stopped to prevent concurrent trading.' >&2
  exit 1
fi
echo 'NBA timer active; NFL timer stopped. Inspect NBA DECISION and last_scan.json.'
