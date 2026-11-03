#!/usr/bin/env bash
# Owner setup for the NBA bot's own server feed (deploy/NBA_SERVER_FEED.md).
# Run as root in the DigitalOcean console:
#   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_nba_feed.sh
#       first run: creates /etc/market-maker-odds.env for the Odds API key;
#       after the key is pasted: installs and starts the sportsbook-lines job
#       (every 20 minutes)
#   ... setup_nba_feed.sh --with-projections
#       also the NBA model-inputs job (4 times a day); refuses without spare memory
#   ... setup_nba_feed.sh --status     what ran, when, and how fresh the feed is
#   ... setup_nba_feed.sh --off        both jobs off (the bot falls back to GitHub)
# Never touches the trading bots, their timers, journals, Kalshi settings or orders.
set -Eeuo pipefail
umask 077

[[ "$EUID" == 0 ]] || { echo "Run with sudo" >&2; exit 2; }
ROOT=/home/trader/sports-market-maker-prod-auto
FEED=/home/trader/nba-feed
ENV=/etc/market-maker-odds.env
BOOKS=market-maker-nba-feed-books
PROJ=market-maker-nba-feed-projections
MIN_AVAILABLE_KB=1600000 # the model step peaks near 900 MB; leave room for the bots
tgit() { runuser -u trader -- git -C "$ROOT" "$@"; }
# Print journal lines without anything that could be a key.
clean() { sed -E 's/(apiKey|ODDS_API_KEY)=[^&" ]*/\1=REDACTED/g'; }

feed_status() {
  for unit in "$BOOKS" "$PROJ"; do
    echo "$unit: timer $(systemctl is-active "$unit.timer" 2>/dev/null || true)," \
      "last run $(systemctl show "$unit.service" -p Result --value 2>/dev/null || true)"
  done
  runuser -u trader -- env PYTHONPATH="$ROOT" PYTHONDONTWRITEBYTECODE=1 \
    "$ROOT/.venv/bin/python" - "$FEED" <<'PY' || true
import json, sys
from datetime import UTC, datetime
from pathlib import Path
from live.nba_inputs import newest_line
feed = Path(sys.argv[1])
now = datetime.now(UTC)
book = feed / "outputs/books/nba_latest.csv"
stamp = newest_line(book.read_bytes()) if book.exists() else None
print("Newest sportsbook line:", f"{(now - stamp).total_seconds() / 60:.0f} minutes old" if stamp else "none yet")
meta = feed / "published/latest_meta.json"
if meta.exists():
    m = json.loads(meta.read_text())
    made = datetime.fromisoformat(m["generated_utc"])
    print(f"Published NBA inputs: {(now - made).total_seconds() / 3600:.1f} hours old, {m['rows']} markets")
else:
    print("Published NBA inputs: none (the bot uses GitHub's)")
PY
  journalctl -u "$BOOKS.service" -n 40 --no-pager -o cat 2>/dev/null \
    | grep -E '^\{"sport"|no game within|error' | tail -n 2 | clean || true
}

case "${1:-}" in
  --off)
    systemctl disable --now "$BOOKS.timer" "$PROJ.timer" 2>/dev/null || true
    echo "NBA server feed is OFF. The NBA bot falls back to GitHub's copies."
    exit 0 ;;
  --status) feed_status; exit 0 ;;
  ""|--with-projections) ;;
  *) echo "Usage: setup_nba_feed.sh [--with-projections|--status|--off]" >&2; exit 2 ;;
esac
WITH_PROJECTIONS=0
[[ "${1:-}" == "--with-projections" ]] && WITH_PROJECTIONS=1

# Never run while a code release is changing the checkout.
exec 9>/run/lock/smm-production-release.lock
flock -n 9 || { echo "A code release is running; try again in a few minutes." >&2; exit 1; }

case "$(tgit remote get-url origin)" in
  https://github.com/akilatrades/sports-market-maker|https://github.com/akilatrades/sports-market-maker.git) ;;
  *) echo "The checkout's origin is not the project repository; refusing." >&2; exit 1 ;;
esac
[[ -z "$(tgit status --porcelain --untracked-files=no)" ]] || {
  echo "The server checkout has local changes; refusing. Deploy cleanly first." >&2; exit 1; }
[[ -f "$ROOT/live/nba_feed.py" ]] && grep -q "def from_feed" "$ROOT/live/nba_inputs.py" || {
  echo "Deploy the code first (Deploy funded worker code -> DEPLOY_CODE)." >&2; exit 1; }

# Units from GitHub main (guards against edits to copies on this server).
tgit fetch --quiet origin main
for f in "$BOOKS.service" "$BOOKS.timer" "$PROJ.service" "$PROJ.timer"; do
  tgit cat-file -e "FETCH_HEAD:deploy/$f" 2>/dev/null || {
    echo "deploy/$f is not on GitHub main yet: merge the pull request first." >&2; exit 1; }
  tgit show "FETCH_HEAD:deploy/$f" > "/etc/systemd/system/$f"
  chown root:root "/etc/systemd/system/$f"
  chmod 644 "/etc/systemd/system/$f"
done
systemctl daemon-reload
install -d -o trader -g trader -m 700 "$FEED"
echo "Units installed from GitHub main $(tgit rev-parse --short FETCH_HEAD); server code at $(tgit rev-parse --short HEAD)."

if [[ ! -f "$ENV" ]]; then
  install -m 600 -o root -g root /dev/null "$ENV"
  printf 'ODDS_API_KEY=\n' > "$ENV"
fi
chown root:root "$ENV"
chmod 600 "$ENV"
if ! grep -Eq '^ODDS_API_KEY=[A-Za-z0-9]{20,}$' "$ENV"; then
  echo "STEP 1 DONE. Now open the key file:"
  echo "  sudo nano $ENV"
  echo "Paste your Odds API key right after ODDS_API_KEY= (no spaces or quotes),"
  echo "save (Ctrl+O, Enter) and exit (Ctrl+X). Then run this script again."
  exit 0
fi

echo "Fetching sportsbook lines once now..."
if systemctl start "$BOOKS.service"; then
  systemctl enable --now "$BOOKS.timer" >/dev/null 2>&1
  echo "OK: sportsbook lines now refresh on this server every 20 minutes."
else
  journalctl -u "$BOOKS.service" -n 8 --no-pager -o cat | grep -iE "error|odds api" | clean || true
  echo "The sportsbook job failed (reason above). Its timer was NOT turned on." >&2
  echo "Common fix: the key was pasted wrongly in $ENV." >&2
  exit 1
fi

if (( WITH_PROJECTIONS )); then
  available=$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)
  free -h
  if (( available < MIN_AVAILABLE_KB )); then
    echo "Not enough spare memory for the model-inputs job ($((available / 1024)) MB free," >&2
    echo "it needs about $((MIN_AVAILABLE_KB / 1024)) MB). Left OFF: the NBA bot keeps using" >&2
    echo "GitHub's model inputs. Sportsbook lines still come from this server." >&2
    exit 1
  fi
  echo "Building NBA model inputs once now (the first run downloads the box-score"
  echo "history and can take up to 10 minutes)..."
  if systemctl start "$PROJ.service"; then
    systemctl enable --now "$PROJ.timer" >/dev/null 2>&1
    echo "OK: NBA model inputs now also come from this server, 4 times a day."
  else
    journalctl -u "$PROJ.service" -n 8 --no-pager -o cat | grep -iE "error|refus|memory" | clean || true
    echo "The model-inputs job failed (reason above). Its timer was NOT turned on;" >&2
    echo "the NBA bot keeps using GitHub's model inputs." >&2
    exit 1
  fi
fi
feed_status
