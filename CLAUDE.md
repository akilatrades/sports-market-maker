# Notes for AI assistants

Claude Code reads this file at the start of every session in this repository.
People new to the project read [docs/START_HERE.md](docs/START_HERE.md); this
file is the short version for an AI helping them.

## What this project is

- Research and live trading for Kalshi player-prop markets ("Will this player
  score 25+ points?"). The strategy posts **post-only resting NO orders**,
  because the people buying YES at the ask are mostly fans backing a player.
- Fair probability comes from sportsbook odds (de-vigged, at least two books on
  the exact line) or, failing that, the project's stat model. An NBA order
  (rules v5) is one contract, needs 0¢ to 15¢ of estimated edge, goes one cent
  inside the spread 2–6 hours before tip-off, and rests until tip-off.
- Three bots trade one small real-money account from a private server: NBA
  and NFL (live since 19–20 October 2026) and the spread maker (live since
  22 October; rules v2, pregame only, from 23 October), which rests YES
  and NO bids one cent inside 8¢+ spreads in 64 other series. **You cannot
  see the server, the account or its private journals**; only the public
  files here. Questions
  about live results go to the owner. If the owner has added the private
  repo `akilatrades/smm-private-data` to the session, it holds an hourly
  export of live orders, fills and settlements
  (`deploy/PRIVATE_FILL_EXPORT.md`); that data is live, so never mix it with
  replay results, and never copy it into this public repository.
- Read first: `docs/START_HERE.md`, `README.md`, `docs/PROJECT_BRIEF.md`,
  `RESEARCH_LOG.md`, `docs/FORWARD_VALIDATION.md`.

## Hard rules

- Never place, cancel or change orders, and never call Kalshi's order
  endpoints. Research code reads files; it does not trade.
- Never add, print or ask for secrets: API keys, SSH keys, tokens, the
  server's address, account numbers or balances. Never commit raw Odds API or
  Databento data (licensed); derived, aggregated results are fine.
- Do not change risk limits or anything in `live/`, `deploy/` or `.github/`
  unless asked. If asked, state the old value, the new value and why, and add
  tests. Code in `live/`, `kalshi/`, `markets/` and `tools/` runs on the
  funded server after the owner deploys it.
- Never change `deploy/*.service`, `deploy/*.timer` or `requirements.txt`
  casually: the release helper refuses releases that change them.
- Files with a date in the name are records; add a new document instead of
  editing one.
- Changes reach `main` only through pull requests from a fork, reviewed by
  the owner (`CONTRIBUTING.md`).

## Research rules (the important part)

- **Write it down first.** Before a confirmatory test, add an entry to
  `RESEARCH_LOG.md` with the question, the method and the pass/fail bar.
  Label everything else *exploratory*.
- **Count every variant you try** and report the count. Trying many versions
  of a rule on the same data finds false winners. The 2025–26 season is
  in-sample (the rules were chosen on it); 2026–27 is the real test.
- **Use game-clustered statistics** (`kalshi.stats.clustered_mean_t`): props
  in the same game move together. One contract's result has a standard
  deviation of about 44¢, so a 3¢ edge needs about 900 fills for t ≈ 2 if
  fills were independent, and about 1,900 once same-game correlation is
  counted (from the 2025–26 replay).
- **Fills are optimistic.** Historical fills come from public trade prints and
  assume the order was first in line. Use `flow_share` below 1 (for example
  0.25) to see a more realistic case, and say which you used.
- **Never mix simulated and live P&L**, and never present a replay as a
  forecast.

## Commands

```bash
pip install -r requirements.txt ruff==0.11.13
ruff check . && ruff format --check .      # CI pins ruff 0.11.13
pytest -q                                  # offline, a few minutes
python -m research.fill_sizing_replay      # fills, P&L, drawdown by rule set
python -m research.fill_sizing_replay capacity   # contracts-per-order sweep
python -m research.nba_launch_audit        # historical audit
python -m research.scaling                 # bankroll replays
```

## Where things are

- `live/prod_nba_auto.py`: the NBA bot; its limits are the `MAX_*` constants
  near the top. `live/prod_nfl_auto.py` and `live/nfl_policy.py`: NFL.
  `live/prod_spread_auto.py` and `live/spread_policy.py`: the spread maker.
  `live/shared_account_risk.py`: account-wide caps and loss stops.
- `kalshi/`: fees, fills, statistics, sportsbook consensus, signed client.
  `markets/nba/`, `markets/nfl/`: stat models. `research/`: backtests.
- Data for research:
  - `outputs/decompose/orders_no.csv.gz`: one row per 2025–26 NBA prop
    market with the hypothetical resting NO order (price, model probability,
    outcome).
  - `data/kalshi_history/trades_*.parquet`: Kalshi's public trade prints.
  - `outputs/bookline/fills_with_book.csv.gz`: fills matched to sportsbook
    lines.
- Current limits: `docs/START_HERE.md#current-live-limits` (the code wins if
  they disagree).

## Open questions worth working on

1. Do live fills match the replay? (Biggest unknown.)
2. What share of the trading at our price do we really get, and how large can
   orders get before fills thin out?
3. Does the edge hold up out-of-sample in 2026–27?
4. Which other markets (stat types, NFL, other sports) show the same pattern?

## Writing style

Plain language. Explain jargon the first time. Give numbers with units and
say whether they are in-sample, simulated or live.
