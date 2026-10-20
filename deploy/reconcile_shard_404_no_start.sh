#!/usr/bin/env bash
# Post-404 exchange-shard recovery. No timers, trading or account transfers.
set -Eeuo pipefail
umask 077
[[ $(id -u) -eq 0 ]] || { echo "Root required"; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
cd "$ROOT"
for unit in market-maker-prod-nba-auto.timer market-maker-prod-nfl-auto.timer \
            market-maker-prod-nba-auto.service market-maker-prod-nfl-auto.service; do
    state=$(systemctl is-active "$unit" || true)
    case "$state" in
        inactive|failed|unknown) ;;
        *) echo "ABORT: worker or timer not stopped ($unit: $state)"; exit 2 ;;
    esac
done
runuser -u trader -- .venv/bin/python -m pytest -q \
    tests/test_shard_funding.py \
    tests/test_reconcile_shard_404.py \
    tests/test_reconcile_rejected_nba.py \
    tests/test_diagnose_uncertain_orders.py \
    tests/test_shared_account_risk.py \
    tests/test_trading.py
systemd-run --wait --pipe --collect --uid=trader \
    -p WorkingDirectory="$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-auto.env \
    "$ROOT/.venv/bin/python" -m tools.reconcile_shard_404 --confirm-shard-404
echo "SHARD REJECTION RECONCILED. TIMERS STILL OFF. Do not restart until shard 3 has funds and new preflight passes."
