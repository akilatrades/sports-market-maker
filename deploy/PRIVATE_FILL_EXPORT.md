# Private fills export (owner setup, about 10 minutes)

Every hour the server copies the bots' live orders, fills and settlements into
a **private** GitHub repository, so the owner (and Claude, when that repository
is added to a session) can study real results without the Kalshi key ever
leaving the server.

- **What it reads:** only the two bot journals (`/home/trader/prod-nba-auto/`
  and `/home/trader/prod-nfl-auto/journal.jsonl`). No Kalshi request, no Kalshi
  credentials. It writes nothing on the server (systemd makes `/home`
  read-only for it).
- **What it sends:** daily CSV files of orders, fills and settled markets, and
  a summary (`tools/export_private_fills.py`, explicit column lists). Exchange
  order and fill IDs become short one-way hashes. No keys, balances or account
  numbers.
- **Where:** only the repository in `PRIVATE_EXPORT_REPO`, using a token that
  can touch nothing else. The export refuses to send anything unless GitHub
  reports that repository as private, and never to `sports-market-maker`.
- It is separate from the trading bots: its own service and timer
  (`market-maker-private-export`), and it never starts, stops or changes them.
  It cannot crowd them out either: memory is capped at 192 MB, it is the
  first process killed if the server runs short, and it gets the lowest CPU
  and disk priority. (A 79 MB journal, several seasons of orders, peaks at
  about 120 MB and takes about 6 seconds.)
- It also refuses a repository that is internal, archived, renamed or has
  GitHub Pages turned on, and never follows a redirect (which could carry the
  token elsewhere). The setup script installs the timer files exactly as they
  are on GitHub `main`, not from copies on the server.

## 1. Create the private repository (GitHub website)

1. github.com → **+** → **New repository**.
2. Name: `smm-private-data`. Choose **Private**. Tick **Add a README file**
   (the export needs a first commit to build on). **Create repository**.
3. Never make it public, and never turn on GitHub Pages for it.

## 2. Create a token that can only write to that repository

1. github.com → your photo → **Settings** → **Developer settings** →
   **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. Name `smm private export`; expiration up to one year (put a reminder in
   your calendar to renew it).
3. **Repository access: Only select repositories** → `smm-private-data`.
4. **Permissions → Repository permissions → Contents: Read and write.**
   Leave everything else as it is.
5. **Generate token** and copy it. Do not paste it into chats, Claude,
   GitHub issues or anywhere else; it goes only into the server file below.

## 3. Deploy the code

Merge the pull request, then run **Deploy funded worker code → DEPLOY_CODE**
(no STOP needed; resting orders stay up).

## 4. Install it on the server (DigitalOcean console)

```bash
sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_private_export.sh
sudo nano /etc/market-maker-private-export.env
```

In the editor, paste the token right after `PRIVATE_EXPORT_TOKEN=` (no
spaces), check `PRIVATE_EXPORT_REPO=akilatrades/smm-private-data`, then save
(Ctrl+O, Enter) and exit (Ctrl+X). Run the script once more:

```bash
sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_private_export.sh
```

It runs one export as a test, shows a one-line count (no data), and turns on
the hourly timer. The private repository should now have a `data/` folder.

To turn it off: `sudo bash .../deploy/setup_private_export.sh --off`.
To stop it for good, also delete the token on GitHub.

## 5. Let Claude read it

On GitHub: **Settings → Applications → Claude → Configure → Repository
access**, and add `smm-private-data` (if access is limited to selected
repositories). Then ask Claude in a session to add
`akilatrades/smm-private-data`.

## Notes

- **Live, not replay.** These files are live results; never mix them with the
  replay's simulated P&L.
- **Timing:** one export per hour. A fill shows up after the bot's next pass
  has journaled it and the next export runs; settlements arrive after games.
- **If an export fails**, `journalctl -u market-maker-private-export -n 5`
  shows a one-line reason (never the token or data). The trading bots are
  unaffected either way.
