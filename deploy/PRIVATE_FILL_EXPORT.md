# Private fills export (owner setup, about 10 minutes)

Every hour the server copies the bots' live orders, fills and settlements into
a **private** GitHub repository, so the owner (and Claude, when that repository
is added to a session) can study real results without the Kalshi key ever
leaving the server.

- **What it reads:** only the bot journals (`/home/trader/prod-nba-auto/`,
  `/home/trader/prod-nfl-auto/` and `/home/trader/prod-spread-auto/journal.jsonl`)
  and the spread maker's shadow ledger (`prod-spread-auto/shadow.jsonl`,
  summarized separately and labelled simulated). No Kalshi request, no Kalshi
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
  It cannot crowd them out either: memory is capped at 768 MB, it is the
  first process killed if the server runs short, and it gets the lowest CPU
  and disk priority. Memory grows with the number of orders, almost all of
  them the spread maker's; see [Memory](#memory) for the numbers and for
  what to do before the cap is reached again.
- It also refuses a repository that is internal, archived, renamed or has
  GitHub Pages turned on, and never follows a redirect (which could carry the
  token elsewhere). If a journal ever shows fewer orders or older data than
  what is already exported (a replaced or restored journal), it pushes
  nothing and reports why. The setup script installs the timer files from
  GitHub `main` (a guard against accidental edits to the server's copies,
  not against someone who already controls the server's `trader` account).

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

## Memory

The export reads each journal from the start and holds every order while it
builds the files, so the memory it needs grows with the bots' history.

- **How much:** about 35 MB plus 3.6 KB per spread-maker order: 338 MB at
  85,138 orders, 640 MB at 170,000 and 944 MB at 255,000. Measured offline on
  22 November 2026 with a journal rebuilt from the exported order rows, and
  without the spread maker's shadow and measurement files, so the server's
  figure is somewhat higher. The NBA and NFL journals are small beside it
  (about 2,000 orders in a month).
- **The limits** (`deploy/market-maker-private-export.service`): the export
  is slowed above `MemoryHigh=640M` (about 170,000 spread orders) and killed
  at `MemoryMax=768M` (about 205,000). The spread maker has placed 3,400 to
  4,800 orders a day, so counting from 85,000 on 20 November the slow-down
  point is about two and a half to three and a half weeks away, and the hard
  limit three and a half to five.
- **What happened in November 2026:** the limits were 160 MB and 192 MB, set
  when the estimate was 5 KB an order and the journal was small, with a note
  to raise them before 25,000 spread orders. The journal passed that
  unnoticed: at 85,138 orders the export needed about 338 MB against a
  192 MB cap. Exports went from 24 a day to 19, 10, 4, 1 and 1 (16 to 20
  November) and then stopped. The bots do not depend on the export and
  carried on.
- **How to see it coming:** `orders` for `spread` in `data/summary.json` in
  the private repository. Raise both limits, or make the export hold less for
  each order, **before it passes about 150,000**. Fewer exports in a day than
  hours is the first sign that it is already too late.
- **To change the limits:** edit the two lines in a pull request, merge it,
  then run the setup script again on the server (section 4; the token stays
  as it is). It installs the new limits from GitHub `main`, runs one export
  as a test and prints a one-line count.
