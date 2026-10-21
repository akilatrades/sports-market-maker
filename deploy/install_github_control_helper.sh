#!/usr/bin/env bash
# One-time owner-run installation of the Go live / Stop helper from a pinned
# public commit. Run from the DigitalOcean root console:
#   bash install_github_control_helper.sh <reviewed 40-character main SHA> [--replace]
# Installs /usr/local/sbin/smm-prod-control (root-owned) and lets the trader
# account run ONLY that fixed path through sudo. It never reads or writes
# Kalshi credentials, never enables a timer and never submits an order.
set -Eeuo pipefail
umask 077
[[ "$EUID" -eq 0 ]] || { echo "Run this installer from the root Droplet console" >&2; exit 2; }
[[ "$#" -ge 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Pass one reviewed 40-character commit SHA" >&2; exit 2; }
SHA="$1"
REPLACE="${2:-}"
[[ -z "$REPLACE" || "$REPLACE" == --replace ]] || { echo "Unknown option" >&2; exit 2; }
SRC=https://raw.githubusercontent.com/akilatrades/sports-market-maker
DEST=/usr/local/sbin/smm-prod-control
POLICY=/etc/sudoers.d/smm-github-control
TMP="$(mktemp /tmp/smm-prod-control.XXXXXXXX)"
SUDO_TMP="$(mktemp /etc/sudoers.d/smm-github-control.XXXXXXXX)"
cleanup() { rm -f "$TMP" "$SUDO_TMP"; }
trap cleanup EXIT

curl --proto '=https' --tlsv1.2 -fsSL "$SRC/$SHA/deploy/smm-prod-control.sh" -o "$TMP"
bash -n "$TMP"
grep -q '^# Root-owned Go live / Stop control' "$TMP" || { echo "Unexpected helper content" >&2; exit 1; }
id -u trader >/dev/null 2>&1 || { echo "Missing trader account" >&2; exit 2; }

printf '%s\n' "trader ALL=(root) NOPASSWD: $DEST *" > "$SUDO_TMP"
chmod 0440 "$SUDO_TMP"
visudo -cf "$SUDO_TMP" >/dev/null

if [[ -e "$DEST" || -e "$POLICY" ]] && [[ "$REPLACE" != --replace ]]; then
  echo "A control helper is already installed; rerun with --replace to update it" >&2
  exit 1
fi
install -o root -g root -m 0700 "$TMP" "$DEST"
install -o root -g root -m 0440 "$SUDO_TMP" "$POLICY"
visudo -c >/dev/null
echo "READY: Go live / Stop helper installed from $SHA."
echo "No timers, orders, credentials or risk settings were changed."
echo "Use GitHub Actions > Go live / Stop funded bots > Run workflow."
