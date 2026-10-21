#!/usr/bin/env bash
# Read-only and deliberately redacted inventory for GitHub Actions diagnostics.
# Never print environment variable values, unit contents, process arguments, or logs.
set -euo pipefail

echo "inventory_utc=$(date -u +%FT%TZ)"
echo "ssh_user=$(id -un)"
echo "host_os=$(uname -s)"
echo "systemd_services:"
for unit in market-maker.timer market-maker.service market-maker-prod-nba-auto.service market-maker-prod-nba-auto.timer market-maker-prod-nfl-auto.service market-maker-prod-nfl-auto.timer prod-nba-auto.service prod-nba-auto.timer prod-nfl-auto.service prod-nfl-auto.timer market-maker-dashboard.service market-maker-live-pnl.service; do
  active=$(systemctl is-active "$unit" 2>/dev/null || true)
  enabled=$(systemctl is-enabled "$unit" 2>/dev/null || true)
  result=$(systemctl show "$unit" --property=Result --value 2>/dev/null || true)
  printf '%s active=%s enabled=%s result=%s\n' "$unit" "$active" "$enabled" "$result"
done

echo "related_unit_names:"
systemctl list-unit-files --no-legend --no-pager 2>/dev/null \
  | awk 'tolower($1) ~ /(market-maker|kalshi|nba|nfl|sports-market)/ {print $1}' \
  | sort -u | head -60

echo "installed_unit_worker_modules:"
for unit in market-maker-prod-nba-auto.service market-maker-prod-nfl-auto.service market-maker.service; do
  path=$(systemctl show "$unit" --value --property=FragmentPath 2>/dev/null || true)
  if [ -n "$path" ] && [ -r "$path" ]; then
    printf '%s unit_file_readable=yes\\n' "$unit"
    for module in live.prod_nba_auto live.prod_nfl_auto live.nba_trade; do
      if grep -Fq "$module" "$path"; then
        printf '%s points_to=%s\\n' "$unit" "$module"
      fi
    done
  else
    printf '%s unit_file_readable=no\\n' "$unit"
  fi
done

echo "candidate_repository_locations:"
for directory in \
  /home/trader/sports-market-maker \
  /opt/sports-market-maker \
  /srv/sports-market-maker \
  /root/sports-market-maker; do
  if [ -d "$directory" ]; then
    printf '%s exists=yes\n' "$directory"
    if [ -d "$directory/.git" ]; then
      revision=$(git -C "$directory" rev-parse --verify HEAD 2>/dev/null || true)
      printf 'repo_commit=%s\n' "${revision:-unavailable}"
    fi
    for f in live/prod_nba_auto.py live/prod_nfl_auto.py live/nba_trade.py; do
      if [ -f "$directory/$f" ]; then
        printf 'worker_present=%s/%s\n' "$directory" "$f"
      fi
    done
  fi
done

echo "runner_classification:"
for script in /home/trader/run.sh /opt/market-maker/run.sh /srv/market-maker/run.sh; do
  if [ -f "$script" ]; then
    printf '%s present=yes\n' "$script"
    for module in live.nba_trade live.prod_nba_auto live.prod_nfl_auto; do
      if grep -Fq "$module" "$script"; then
        printf 'runner_module=%s\n' "$module"
      fi
    done
  fi
done

echo "candidate_state_locations:"
for directory in /home/trader/prod-nba-auto /home/trader/prod-nfl-auto /home/trader/sports-market-maker /opt/market-maker; do
  if [ -d "$directory" ]; then
    printf '%s exists=yes\n' "$directory"
    for f in journal.jsonl KILL run.sh .venv/bin/python; do
      if [ -e "$directory/$f" ]; then
        printf '%s present=%s\n' "$directory" "$f"
      fi
    done
  fi
done

echo "unit_timing:"
systemctl show market-maker.timer --property=LastTriggerUSec --property=NextElapseUSecRealtime --no-pager 2>/dev/null || true

echo "remote_access_scope:"
if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
  echo "passwordless_sudo=yes"
else
  echo "passwordless_sudo=no"
fi
