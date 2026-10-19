# Tuesday, October 20, 2026 — NBA production GO / NO-GO

> **This is an owner-controlled bounded real-money PILOT**, not an instruction
> to trade regardless of conditions. Never activate both NFL and NBA on one
> account. Do not increase any caps, bypass sportsbook/news vetoes, reset
> journals, remove a KILL file, or restart an uncertain submission.

For full context: [living state](CURRENT_PROJECT_STATE.md),
[production handoff procedure](../deploy/PROD_NBA_AUTO.md),
[research audit](NBA_AND_MARKET_AUDIT_2026-10-18.md).

## The business question

Can a model + fresh, exact-line independent sportsbook consensus identify
passive NO orders on Kalshi that actually **fill** and earn **positive
settled dollars after costs** at a small stake? One profitable game would
prove little. Queue priority, adverse fills, fees, repeated independent
games and capital capacity matter. A $50 cumulative gross-submission
pilot tests infrastructure and collects initial evidence, not a paycheck.

## Monday 10/19 checkpoint: public data only

- NBA model **312** current Kalshi prop quotes, 2026-10-19 12:06 UTC,
  `nba-opening-v2` with checksum metadata.
- The latest reviewed books at 12:48 UTC contained **823** sportsbook
  player-prop consensus lines across Boston–Detroit and
  Philadelphia–New York; **309** had >=2 books.
- **71** exact player/stat/line/game-day model matches with >=2 books:
  **29** DET/BOS, **42** NY/PHI, **0** SA/OKC as of that snapshot.
- These are **source-data join counts, not vetted trade candidates or
  profit forecasts**. Source quotes expire after FOUR hours, and the
  trading worker recomputes live venue quotes, injuries, final fee bounds,
  roster and game matching on each order scan.
- A read-only production account check at **12:36 UTC** returned
  **zero held positions and zero resting orders**, with ten previously
  accepted NFL orders in its historic journal. The account might change
  after that check while the NFL timer remains active.
- Current approved production code on Droplet in last owner screenshot
  was `f31ce87`, which includes staged NBA. Later GitHub-only changes
  to book scheduling and docs do NOT imply new trading code deployment.
- NBA service and timer were **inactive**, with zero real NBA orders.

## Launch clock (US Central daylight time, UTC-05)

| Tue game | Tip-off | Maker entry window |
|---|---|---|
| Boston @ Detroit | 2:00 PM | 8:00 AM–12:00 PM |
| Philadelphia @ New York | 6:00 PM | 12:00–4:00 PM |
| Oklahoma City @ San Antonio | 8:30 PM | 2:30–6:30 PM |

Orders expire within one hour and **before** the final two hours. The
worker rejects POSTs within an additional 30-second safety buffer.

## Monday: evidence preparation (NO ARM)

1. Check **GitHub Actions > book lines** and
   `outputs/books/nba_latest.csv`: look for three games and >=2 exact
   fresh books on at least some live Kalshi player/stat/threshold matches.
   Sportsbook feed discovery may lag as each game enters a 36h lookahead.
   A nonempty file **is not** exchange-confirmed profitability.
2. From DigitalOcean, re-sync the latest pinned model/book input bundle,
   then inspect its freshness and coverage:

   ```bash
   cd /home/trader/sports-market-maker-prod-auto
   sudo -u trader .venv/bin/python -m live.nba_inputs --sync /home/trader/prod-nba-auto/inputs
   sudo -u trader .venv/bin/python -m tools.production_status
   ```

3. Run the **signed, READ-ONLY** NBA preflight below to test rosters,
   fixture matches, quote freshness, two-book requirements, Kalshi
   credentials and risk status. The NFL timer is expected to cause
   `NFL production still active` until the handoff. Do not stop the
   NFL timer merely to turn a report green.

   ```bash
   cd /home/trader/sports-market-maker-prod-auto
   sudo systemd-run --wait --pipe --collect \
     --uid=trader \
     -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
     -p EnvironmentFile=/etc/market-maker-prod-nba-auto.env \
     /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
     -m live.prod_nba_auto --preflight --sync-inputs
   ```

4. Refresh the **authenticated sanitized NFL fills+settlements** and
   reconcile the two formerly-unsettled Matthew Golden positions. A flat
   position is NOT settlement P&L. Keep NBA and NFL results separate.

## Tuesday: GO / NO-GO before 8 AM Central (OWNER DECISION)

**GO is allowed only when ALL of these are true**:

- Latest merged trading code is verified and tested; deployed worker SHA
  and protected env match approved code. **No live-service surprise**.
- A model CSV + SHA metadata downloaded successfully, is within the
  **nine-hour age limit**, and matches the current official schedule.
- The book file contains **individually fresh** quote timestamps
  within **four hours**, exact player/stat/line, correct game and at
  least **two independent books** where `requires_book=True`.
  Book quote time may need to be newer than relevant injury news.
- Current **signed GET-only** preflight reports no unknown
  orders/positions, sufficient cash and lifetime budget, no unexpected
  fee metadata, verified fixture/roster/injury feeds and suitable model
  rows. A positive edge is rechecked against live quotes and actual
  maker-fee bound immediately prior to every POST.
- NFL-to-NBA account isolation is deliberate. No NFL active service,
  timer or outstanding exposures may coexist with the independent NBA
  risk manager. The preflight must be repeated **after stopping NFL**.
- No KILL flag, uncertain placement or reconciliation mismatch.
- Owner explicitly chooses to enable the existing **bounded $50 pilot**,
  understanding all submitted cost is at risk and it is not income.

**DO NOT ACTIVATE** on a partial pass. If the above conditions are
satisfied and the owner wants to begin the pilot, the existing
`deploy/activate_nba_auto.sh` implements the handoff by pausing NFL,
checking the account and preflight, and enabling NBA only on success.
It restores the earlier NFL timer if preflight fails, with caveats
documented in [the official deployment guide](../deploy/PROD_NBA_AUTO.md).

Do NOT run `activate_nba_auto.sh` simply to try for fills; no guaranteed
orders will result even on a successful activation.

## Fixed risk limits (do not increase for opening night)

- NO post-only orders; up to **one new order per five-minute scan**
  and **one lifetime submission per ticker**.
- **$3 maximum gross/reserved per order, game and team**,
  **$15 active**, **$30/day**, **$50 lifetime submitted allowance**.
- Five contracts maximum/order, two orders/game; 10% sizing reserve;
  maker-only re-quote/passivity check and final positive after-fee edge.
- Extra price improvement is conditional, **not** a reason to assume
  faster fills. Unknown exchange outcome fails closed.

## After the first accepted order

Record distinct counts of intents, exchange accepted, resting, real
maker/taker fills, partial fills, expiries, and unmatched positions.
Wait for exchange settlement before calling a profit realized.
Measure return by independent game and dollar cost, including **zero-fill
opportunities**, and keep private account identifiers/secrets off GitHub.

**If sportsbook lines, injury data, cash, or account-isolation conditions
fail during Tuesday's windows, the correct outcome is ZERO trades.**
Missing a slate is less costly than using unverified stale prices.
