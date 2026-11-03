# The NBA bot's own server feed (no GitHub scheduler)

**Why.** The NBA bot needs two inputs: sportsbook prop lines (to price every
order; new orders need lines under 60 minutes old, resting orders under 120)
and the NBA model inputs (tonight's Kalshi markets with player and game
context, under 9 hours old). Both came only from GitHub's scheduled
workflows, and GitHub skipped most of those runs: on 2 November its
20-minute sportsbook job ran 3 times between 14:00 and 04:00 UTC, so 85% of
resting NBA orders were cancelled on stale prices; on 3 November no model
inputs were published until the owner ran the job by hand.

**What.** Two jobs on the server, each with its own systemd timer, run as the
`trader` user from `/home/trader/nba-feed` (`live/nba_feed.py`):

| Job | Timer | What it does | Needs |
|---|---|---|---|
| `market-maker-nba-feed-books` | every 20 minutes (:05, :25, :45 UTC) | sportsbook NBA prop lines for games within 6.5 hours (`live.log_books`, near scope) | `ODDS_API_KEY` in `/etc/market-maker-odds.env` |
| `market-maker-nba-feed-projections` (optional) | 10:20, 12:20, 15:20, 18:20, 21:20 UTC | box-score history (every run, as on GitHub), then the model inputs for every open market; published to `published/` only after the same check GitHub uses (`live.nba_publish_check`) | about 1.6 GB of free memory to install; a run is skipped if under 1.2 GB is free |

Each NBA pass (`live.nba_inputs.sync`) takes the newest valid copy of each
input from three places: the server's feed, GitHub, and the copy the bot
already holds, so a failed or older source never rolls it back. Sportsbook
lines are refreshed even when no model-inputs copy is valid (fresh server
lines keep flowing while GitHub is down). If a server job fails, the last
good copy (or GitHub's) is used and the bot's own age limits still apply. A
broken file is ignored, never repaired. Each pass logs where each input came
from (`NBA INPUTS: model inputs from ...; sportsbook lines from ...`).

**Safety.** No Kalshi credentials and no order code: only public reads plus
the Odds API. The jobs cannot write the trading checkout or journals
(`ProtectHome=read-only`; only `/home/trader/nba-feed` is writable), so they
can never block a code release; they cannot read the bots' journals either,
and they skip a run while a code release holds its lock. Memory is capped with no swap and the jobs
are the first the kernel kills (books 320 MB, model inputs 1.3 GB; the model
step peaked near 900 MB offline), at the lowest CPU and disk priority. The
feed deletes its own dated files after 14 days.

**Odds API credits.** About 8 credits per NBA game per refresh (as on
GitHub). A game is refreshed about 20 times in its 6.5-hour window, so a
10-game night is roughly 1,600 credits; nothing is spent when no game is
within 6.5 hours. `--status` prints the credits left after the last fetch.
GitHub's own 20-minute job (`.github/workflows/books.yml`, near scope) still
runs with the same key whenever GitHub schedules it, so both together could
spend about twice that if GitHub's scheduler recovers. Once the server feed
has run cleanly for a day, turn GitHub's near-scope schedule off.

## Install (owner, DigitalOcean console)

1. Merge the pull request, then run *Deploy funded worker code* with
   `DEPLOY_CODE`.
2. `sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_nba_feed.sh`
   creates `/etc/market-maker-odds.env` (root only).
3. `sudo nano /etc/market-maker-odds.env`, paste the key after
   `ODDS_API_KEY=`, save (Ctrl+O, Enter), exit (Ctrl+X).
4. Run the script again: it fetches lines once and turns the 20-minute timer
   on.
5. Optional: `... setup_nba_feed.sh --with-projections` also builds the model
   inputs on the server. It refuses if less than about 1.6 GB of memory is
   free, and then the bot keeps using GitHub's model inputs.

`--status` shows both timers, the age of the newest sportsbook line and of
the published model inputs; `--off` turns both jobs off and sets their data
aside, so the bot falls back to GitHub straight away.

## Readiness on days with no NBA props

Since 3 November the NBA readiness check (`--preflight`, run by every code
release while the NBA timer is on) treats a checked, fresh, empty set of
model inputs whose metadata says Kalshi listed no NBA props
(`open_markets` = 0) as idle (`idle_reason: no_nba_markets_listed`) rather
than a failure. Before, every release failed on such days (Election Day,
3 November). Stale inputs, or open props with no priced rows, still fail.
The same check gates arming (Go live); on such a day it verifies only the
account reads, while every order still checks its own funding when placed.
`open_markets` = 0 cannot tell "no props listed" from a Kalshi market list
that came back empty because of an error; either way nothing can be traded.
