#!/usr/bin/env bash
# Safe, READ-ONLY preparation for a free sslip.io Kalshi P&L hostname.
# No secret reads, firewall edits, installations, trading or service changes.
set -euo pipefail

echo "FREE P&L HTTPS PREFLIGHT — no changes will be made"
ip=$(curl -fsS --max-time 10 https://api.ipify.org | tr -d '\r\n')
if [[ ! "$ip" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; then
  echo "Could not validate public IPv4 address; STOP."
  exit 2
fi
IFS='.' read -r a b c d <<< "$ip"
for octet in "$a" "$b" "$c" "$d"; do
  if ((10#$octet > 255)); then
    echo "Invalid IPv4 address; STOP."
    exit 2
  fi
done
host="${ip//./-}.sslip.io"
echo "Proposed zero-cost public hostname: $host"
echo "Future HTTPS route (not enabled yet): https://$host/v1/pnl"
dns=$(getent ahostsv4 "$host" | awk 'NR==1 {print $1}' || true)
if [[ "$dns" == "$ip" ]]; then
  echo "sslip.io DNS: OK (resolved to the server public IPv4)"
else
  echo "sslip.io DNS: CHECK (resolved=${dns:-unavailable}, expected=$ip)"
  echo "Do NOT request a TLS certificate until DNS resolves correctly."
fi

echo
echo "Current HTTP / HTTPS / P&L listeners:"
if command -v ss >/dev/null 2>&1; then
  ss -ltnp '( sport = :80 or sport = :443 or sport = :8765 or sport = :8766 )' || true
else
  echo "ss unavailable; check listeners manually before installing Caddy"
fi

echo
echo "Installed web proxy:"
for proxy in caddy nginx apache2; do
  if command -v "$proxy" >/dev/null 2>&1; then
    echo "Found: $proxy"
  fi
done

echo
echo "Read-only P&L service status:"
systemctl is-active market-maker-live-pnl.service || true

echo
echo "Trading timers (observed only):"
systemctl is-active market-maker-prod-nfl-auto.timer || true
systemctl is-active market-maker-prod-nba-auto.timer || true

echo
echo "The private Kalshi account dashboard must remain on localhost:8765."
echo "Don't open 8765/8766 in DigitalOcean or UFW."
echo "Send this output to ChatGPT before installing or changing HTTPS proxy."
