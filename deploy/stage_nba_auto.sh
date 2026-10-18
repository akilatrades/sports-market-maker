#!/usr/bin/env bash
# Owner-run staging only. Does not start/stop either trading worker.
set -euo pipefail
cd /home/trader/sports-market-maker-prod-auto
if [[ $(id -u) != 0 ]]; then
  echo 'Run this staging script as root.' >&2
  exit 1
fi
if systemctl is-active --quiet market-maker-prod-nba-auto.timer || systemctl is-active --quiet market-maker-prod-nba-auto.service; then
  echo 'NBA is already active. Use a planned maintenance stop before staging.' >&2
  exit 1
fi
install -d -m 700 -o trader -g trader /home/trader/prod-nba-auto
if [[ ! -e /etc/market-maker-prod-nba-auto.env ]]; then
  install -m 600 -o trader -g trader /etc/market-maker-prod-auto.env /etc/market-maker-prod-nba-auto.env
  python3 - <<'PY'
from pathlib import Path
p = Path('/etc/market-maker-prod-nba-auto.env')
overrides = {'KALSHI_ENV':'prod', 'TRADE_MODE':'live', 'TRADE_MARKET':'nba',
             'PROD_NBA_AUTO_ARM':'NO', 'PROD_NFL_AUTO_ARM':'NO',
             'ALLOW_PRODUCTION_TRADING':'YES', 'DEMO_PILOT':'0'}
lines = [line for line in p.read_text().splitlines() if line.split('=',1)[0].strip() not in overrides]
p.write_text('\n'.join(lines + [f'{k}={v}' for k,v in overrides.items()]) + '\n')
PY
fi
install -m 644 deploy/market-maker-prod-nba-auto.service /etc/systemd/system/
install -m 644 deploy/market-maker-prod-nba-auto.timer /etc/systemd/system/
systemctl daemon-reload
echo 'NBA staged. Timer remains stopped. NFL continues in its existing state.'
echo 'Next: read deploy/PROD_NBA_AUTO.md for the owner-run production preflight and handoff.'
