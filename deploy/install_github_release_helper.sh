#!/usr/bin/env bash
# One-time owner-run privileged installation from a pinned public git commit.
# Usage: bash install_github_release_helper.sh <fully-qualified reviewed main SHA>
# Never writes Kalshi credentials or changes trading services.
set -Eeuo pipefail
umask 077
[[ "$EUID" == 0 ]] || { echo "Run this installer from the root Droplet console" >&2; exit 2; }
[[ "$#" == 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "Pass one reviewed 40-character commit SHA" >&2; exit 2; }
SHA="$1"
ROOT=https://raw.githubusercontent.com/akilatrades/sports-market-maker
TMP="$(mktemp /tmp/smm-prod-release.XXXXXXXX)"
SUDO_TMP="$(mktemp /etc/sudoers.d/smm-github-release.XXXXXXXX)"
cleanup() { rm -f "$TMP" "$SUDO_TMP"; }
trap cleanup EXIT
curl --proto '=https' --tlsv1.2 -fsSL \
  "$ROOT/$SHA/deploy/smm-prod-release.sh" -o "$TMP"
bash -n "$TMP"
[[ $(id -u trader) =~ ^[0-9]+$ ]] || { echo "Missing trader account"; exit 2; }
# Limit root escalation to a fixed, root-owned release script.
printf '%s\n' 'trader ALL=(root) NOPASSWD: /usr/local/sbin/smm-prod-release *' > "$SUDO_TMP"
chmod 0440 "$SUDO_TMP"
visudo -cf "$SUDO_TMP" >/dev/null
if [[ -e /etc/sudoers.d/smm-github-release ]]; then
  echo "An existing release sudoers policy was found: inspect before replacing" >&2
  exit 1
fi
if [[ -e /usr/local/sbin/smm-prod-release ]]; then
  echo "An existing release helper was found: inspect before replacing" >&2
  exit 1
fi
install -o root -g root -m 0700 "$TMP" /usr/local/sbin/smm-prod-release
install -o root -g root -m 0440 "$SUDO_TMP" /etc/sudoers.d/smm-github-release
visudo -c >/dev/null
echo "READY: reviewed helper installed. No timers, Kalshi orders, or credentials changed."
echo "Now use GitHub Actions > Deploy funded worker code > Run workflow."
