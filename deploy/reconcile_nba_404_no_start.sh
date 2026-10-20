#!/usr/bin/env bash
# One owner-controlled repair for the October 20 Kalshi API-404 incident.
# Reconciliation is append-only, no Kalshi writes, and timers stay stopped.
set -Eeuo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo "Run with sudo."; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
cd "$ROOT"
for unit in market-maker-prod-nba-auto.timer market-maker-prod-nfl-auto.timer \
            market-maker-prod-nba-auto.service market-maker-prod-nfl-auto.service; do
    case "$(systemctl is-active "$unit" || true)" in
        inactive|failed|unknown) ;;
        *) echo "ABORT: trading service or timer still active: $unit"; exit 2 ;;
    esac
done
echo "Running offline rejection/account regression checks..."
runuser -u trader -- .venv/bin/python -m pytest -q \
    tests/test_reconcile_rejected_nba.py \
    tests/test_diagnose_uncertain_orders.py \
    tests/test_shared_account_risk.py \
    tests/test_prod_nba_auto.py \
    tests/test_prod_nfl_auto.py \
    tests/test_trading.py

JOURNAL=/home/trader/prod-nba-auto/journal.jsonl
[[ -f "$JOURNAL" ]] || { echo "Missing NBA journal"; exit 2; }
BACKUP=/home/trader/prod-nba-auto/journal.before-404-reconciliation.20261020.jsonl
[[ ! -e "$BACKUP" ]] || { echo "Original backup already exists; refusing overwrite."; exit 2; }
cp -p -- "$JOURNAL" "$BACKUP"
chmod 600 "$BACKUP"
echo "Verifying signed Kalshi orders, fills and positions; no exchange writes..."
systemd-run --wait --pipe --collect \
    --uid=trader \
    -p WorkingDirectory="$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-auto.env \
    "$ROOT/.venv/bin/python" -m tools.reconcile_rejected_nba \
    --confirm-kalshi-ui-empty --confirm-original-post-http-404
echo "Rechecking both-sport risk ownership and eligibility..."
systemd-run --wait --pipe --collect \
    --uid=trader \
    -p WorkingDirectory="$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-auto.env \
    "$ROOT/.venv/bin/python" -m tools.dual_account_preflight
systemd-run --wait --pipe --collect \
    --uid=trader \
    -p WorkingDirectory="$ROOT" \
    -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
    "$ROOT/.venv/bin/python" -m live.prod_nba_auto --preflight --sync-inputs
echo "RECONCILIATION VALIDATED. NO TIMERS WERE STARTED. Await explicit owner GO."
