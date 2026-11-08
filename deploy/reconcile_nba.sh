#!/usr/bin/env bash
# Owner command after an "Ambiguous production order" halt caused by an NBA
# order whose outcome is unknown (Kalshi gave no clear answer to it). All
# three bots stay stopped until this runs. Signed GETs only: each such order
# is recorded as placed (found on Kalshi) or never placed (absent after its
# tip-off, with no fill or position on its market). Places, cancels and
# arms nothing; the attempt still counts against every budget.
# RESEARCH_LOG.md, 2026-11-08, "NBA reconcile command". Run as root:
#   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/reconcile_nba.sh
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "Run with sudo" >&2; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
grep -q -- '"--reconcile"' "$ROOT/live/prod_nba_auto.py" || {
  echo "Deploy the code first (Deploy funded worker code -> DEPLOY_CODE)." >&2; exit 1; }

systemd-run --quiet --wait --pipe --collect --uid=trader \
  -p "WorkingDirectory=$ROOT" \
  -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
  -p Environment=OPENBLAS_NUM_THREADS=1 \
  -p Environment=OMP_NUM_THREADS=1 \
  "$ROOT/.venv/bin/python" -m live.prod_nba_auto --reconcile
echo "If bots_can_trade is true: done; then press Go live if NBA/NFL were stopped."
echo "If it says try_again: run this again after that game's tip-off or settlement."
echo "Anything else (check_by_hand, still_blocked_by): stop and ask before trading."
