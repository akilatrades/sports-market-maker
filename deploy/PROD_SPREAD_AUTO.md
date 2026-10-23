# Spread maker pilot (third bot)

`live/prod_spread_auto.py`, strategy version `spread-maker-v3-24h-starts`
(v1 from 22 October, v2 and v3 from 23 October). It posts a
buy order of up to 5 contracts on **both sides** of markets where the gap between the best
bid and the best offer (the *spread*) is 8¢ or more, one cent better than
anyone else on each side. When both orders fill, the bot owns a YES and a NO
contract that together pay exactly $1 and cost less than $1: a locked profit.
When only one fills, it holds that contract to settlement.

Plan and pass/fail bars: `RESEARCH_LOG.md`, "2026-10-22: Spread maker pilot,
shadow and small live (plan)", its implementation notes and the 5-contract
amendment; for v3, "2026-10-23: Spread maker v3" and "Spread maker v3:
changes after review". The evidence is a
**simulated, in-sample** backtest (strategy sweep, family 7). The pilot exists
to find out whether real fills look like the simulated ones; it is not a
profit forecast.

## What it does

- **Markets:** 61 of the 64 series in `live/spread_policy.py` (esports,
  smaller basketball and hockey leagues, cricket, soccer side markets, UFC,
  motor racing and others). Since v3 the Brent, S&P 500 and 10-year note
  dailies (`NO_START_SERIES`) are never quoted: their "start" is a session
  open while the futures trade overnight, so pregame protects nothing.
  Never an NBA or NFL player prop and never a market another bot holds. Series on Kalshi's maker-fee list are skipped;
  `KXNCAAFSPREAD` also turned out to pay a small maker fee, and the owner
  chose to keep it (fees count in realized P&L).
- **When:** markets whose expected expiration is 4 to 24 hours away (v2:
  4 to 7), and **only before the event starts** (pregame since v2). The
  start time:
  1. **Ticker time.** Many tickers carry it, in New York time (e.g.
     `KXR6GAME-26OCT222000...` is 20:00). Such an event uses it, or a
     Kalshi milestone if that is earlier, never the series gap below.
  2. **Otherwise, the earlier of:**
     - a Kalshi milestone of a type validated on past events
       (`baseball_game`, `basketball_game`, `cricket_match`,
       `hockey_tournament`), unless a milestone of that type was seen later
       than a ticker time in the last 2 days (`esports_match` is never
       trusted: it was late on half of past events);
     - for the 31 series in `SERIES_START_OFFSET_HOURS`: expected expiration
       minus the series' gap minus 30 minutes. The gap is the larger of the
       median and the 99th percentile in the scan, rounded up to 15 minutes
       (3 hours for most games, 4 for esports, 6 for `KXNBAPTSLEADER`).
       Checked against 3,798 events whose ticker carries the real start,
       this estimate would have cancelled quotes only after the real start
       for 1 event (simulated, in-sample). If a ticker-timed event in the
       same series shows a longer gap than the table plus 30 minutes, that
       series' gap is not used for two days;
     - any other milestone read for the event, of any type, when it is
       earlier (it never dates an event by itself).
  3. **Never later.** The earliest start found for an event is kept for two
     days (`event_starts.json`, and for events already quoted also in the
     journal), so a delayed expiration or a milestone that cannot be read
     never moves it later.

  A market with no known start is not quoted. Milestone reads (at most 60 a
  pass, none after 45 seconds) go to events with quotes resting, then four
  ticker-timed trust checks, then untimed events in series with a gap, then
  `KXBIG3GAME`. Untimed events in other series are never read: no trusted
  milestone type has ever dated them. A new quote needs the start at
  least 85 minutes away, so its 65-minute life ends 20 minutes before the
  start; any resting quote is cancelled 20 minutes before the start, even
  if the order book cannot be read. v1 had no start check: its window counted only from Kalshi's
  expected expiration, which for college football is 6 hours after kickoff,
  so on 22 October it quoted into a live game.
- **Quote:** YES bid at best YES bid + 1¢, NO bid at best NO bid + 1¢, up to
  5 contracts each, post-only (never takes liquidity), expiring on the exchange
  after 65 minutes. Prices come from the public order book with the bot's own
  orders removed, so it never prices off itself.
- **Inventory:** held plus resting contracts on one side of a market never
  exceed 5. Holding 2 YES, its YES order is for 3; holding 5, it stops
  quoting YES there (NO quotes, which close YES contracts, continue). A
  partly filled order keeps its place in the queue and is not topped up.
- **Every 10 minutes** (minute 3, 13, 23, ...). Each pass also writes the
  **shadow ledger**: the quotes the rule would post on every eligible market,
  scored later from Kalshi's public trade prints. Shadow mode alone uses no
  credentials and places nothing.

## Why live and shadow run together

The shadow ledger assumes we were first in line at our price, so it cannot
tell us our real share of the trading. Only real orders can. Running both on
the same markets lets the owner compare live fills with shadow fills
directly: that comparison is the main point of the pilot.

## Limits (pilot)

| Limit | Spread bot | Notes |
|---|---:|---|
| Contracts per order | up to 5 | 1, then 5 (22 October); the first v3 draft had 2 |
| Net contracts per market and side | 5 | 1, then 5; the first v3 draft had 2 |
| Open exposure (resting orders + held contracts, at cost) | $120 | $25, then $60 until v3 |
| Orders per pass / per New York day | 20 / 1,500 | Cancelled orders still count; 300 a day before v3 (each quote is re-posted at least hourly) |
| Own realized-loss stop, per day / total | −$15 / −$40 | −$5 / −$15, then −$10 / −$40 until v3; cancels its quotes and stops |
| Account realized-loss stop, per day / total | −$20 / −$100 | Shared with NBA and NFL; total was −$60 before 23 October |

- The NBA and NFL caps ($165 open, $180 a day, $5,050 lifetime) are
  unchanged and do not include spread orders. All three bots together can
  have at most $285 open (NBA $150, NFL $15, spread $120) on the $350 account.
- The account stops count realized losses of all three bots, so spread
  losses can stop NBA and NFL for the day, and the reverse. A −$15 spread
  day leaves NBA only $5 of the shared −$20 daily stop.
- **How spread P&L is counted.** Kalshi nets YES against NO, so when both
  quotes fill the pair closes at once and never appears in a settlement
  record. The bot (and the account stop) therefore count its P&L from its
  own fills: a closed pair counts $1 minus both prices the moment the second
  leg fills; a contract still held counts its payout minus its price when the
  market settles. A fill whose side or price disagrees with the journal, or a
  settlement whose payout disagrees with the fills, blocks new orders for all
  three bots until it is explained. Watch the first settled market closely.
  The journal keeps its own copy of every fill and settlement, so the count
  does not depend on how long Kalshi keeps listing old fills.
- Worst plausible case: the $40 own stop is reached and every open position
  then loses: about $40 + $120 = $160 (v2: $100). In the (simulated, in-sample) sizing
  test the worst day was −$16 and the worst drawdown −$18.

## Safety rules (same as the other bots)

- Every order and cancel is written to the journal
  (`/home/trader/prod-spread-auto/journal.jsonl`) before it is sent.
- A placement the exchange refuses with an HTTP 4xx (for example a post-only
  order that would have crossed) is recorded as refused only after signed
  reads find no such order in any status (resting, filled or cancelled).
  **Any other failure halts all three bots** until the owner runs
  `setup_spread_maker.sh --reconcile` (below).
- A pass that halts first cancels the bot's own resting quotes (found by
  journal or by its `smm-spread-` client-id prefix, so this works even if
  the journal is damaged). A brief read failure (timeout, HTTP 429 or 5xx)
  is not a halt: the quotes stay, expire on their own, and the next pass
  checks again.
- A quote that turns out to have filled, fully or partly, just as the bot
  cancels it (the exchange cancels fewer contracts than were resting) is not
  replaced in that pass, and the possibly filled contracts count toward the
  $120 cap, so the cap per market side (5 contracts) holds.
- If a market's order book cannot be read, the bot leaves its quotes there
  alone (they expire on the exchange) and adds nothing new in that market.
- No new order after 110 seconds from the start of a pass (waiting for the
  other bots counts), so systemd's 240-second limit never cuts an order off
  mid-send; a stop signal also lets the order in flight finish first.
- The NBA and NFL workers recognise the spread bot's orders, fills and
  positions through `live/shared_account_risk.py`, and still halt on anything
  unowned. The spread bot needs shared-account mode (`SMM_DUAL_MARKET=YES`
  and `/etc/market-maker-shared-account.enabled`).
- Live orders need **two** owner steps on top of the existing production
  settings: `SPREAD_AUTO_ARM=YES` in `/etc/market-maker-spread.env` and the
  marker `/etc/market-maker-spread.enabled`. The setup script's `--arm` makes
  both after a GET-only preflight.
- A pass is skipped while a code release is updating the server checkout.

## Owner steps

1. Merge the pull request, then run **Deploy funded worker code →
   DEPLOY_CODE** as usual. This only updates the code; the NBA and NFL
   timers are restored as they were.
2. In the DigitalOcean console, start shadow mode (installs the timer from
   GitHub `main` and runs one shadow pass):

   ```bash
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh
   ```

3. Check readiness without trading, then arm:

   ```bash
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --preflight
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --arm
   ```

   A passing preflight shows `"ready": true`, the number of markets that
   qualify right now (often 0 at quiet hours) and whether the account stop
   is active. It prints counts only.

4. Watch it:

   ```bash
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --status
   ```

   This shows the timer, the arm and halt switches, live orders, fills and
   settled P&L, the shadow ledger's fill rate and profit per contract (at
   flow share 1 and 0.25), and the last pass.

## Resuming with v2 (pregame only), after the 22 October pause

1. Merge the v2 pull request and run **Deploy funded worker code →
   DEPLOY_CODE**. The `KILL` file from `--cancel` stays in place, so the
   bot keeps only cancelling.
2. Check readiness (reads only):

   ```bash
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --preflight
   ```

   Look for `"ready": true` and the new `milestone_check`, which compares
   Kalshi's milestone start with the time in the ticker for up to 10
   events: `matched` is good, `later_than_ticker` is the dangerous case.
   `wide_markets_without_event_start` counts wide markets skipped because
   no start is known. Preflight's comparisons are a report only: the bot
   builds its own trust from up to 4 comparisons a pass and distrusts a
   milestone type for two days after any milestone of that type is later
   than a ticker's time. If preflight shows `later_than_ticker` above 0,
   wait a pass, run it again and send the line to whoever maintains the
   code before resuming.
3. Resume and watch the next pass:

   ```bash
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --resume
   sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --status
   ```

   Each pass's report shows `event_starts` (milestone reads, the milestone
   types trusted and any found late; since v3 also how many events were
   dated by a milestone, by a series gap (and how many of those went
   unread) or kept at an earlier start, how many had none, any series
   whose gap is suspended, and `cache_write_failed`) and
   `canceled_event_start`. Expect
   fewer quotes than v1: in the backtest, the v2 rule on events whose
   ticker carries the start kept about a sixth of v1's simulated profit,
   more where milestones are trusted.

## Switching to v3

Merge the v3 pull request and run **Deploy funded worker code →
DEPLOY_CODE**. Nothing else: v2 quotes still resting have the same size
and keep their place until their hourly refresh, when v3 quotes replace
them. Then watch `--status` and the pass report: `event_starts` should show
events dated by a series gap, and `skip_daily_cap` should stay at 0
(`skip_active_cap` above 0 means the $120 cap is binding). v2 measurements still pending when v3
starts are not completed: each rule version is judged on its own orders.

## After an "Ambiguous spread order" halt

All three bots stop placing orders. Run:

```bash
sudo bash /home/trader/sports-market-maker-prod-auto/deploy/setup_spread_maker.sh --reconcile
```

It only reads. For each order the journal cannot prove, it looks the order
up on Kalshi in every status: found means it was placed (recorded as
accepted, so its fills are owned); not found 10 or more minutes after it was
sent means it never reached the exchange. If it says `too_recent`, run it
again in 10 minutes. `"bots_can_trade": true` means the bots resume on their
next passes. Anything else: stop and look before trading again.

## Switching off

| Command | Effect |
|---|---|
| `--disarm` | No new orders. Resting quotes expire within 65 minutes. Shadow keeps running. |
| `--cancel` | Cancels the bot's resting orders now and leaves a `KILL` file, so every pass only cancels. `--resume` removes it. |
| `--off` | `--disarm` + `--cancel`, then stops the timer (shadow stops too). |

The **Go live / Stop funded bots** workflow and the code release helper
manage the NBA and NFL timers only; neither stops the spread bot. Use this
script for the spread bot. The account loss stops do apply to all three.
During a code release the spread bot skips its passes, and the release's
read-only account checks wait for any spread pass in progress (they take
the account lock).

## Where its results appear

- **Private fills export** (`smm-private-data`, hourly): `data/spread/` with
  orders, fills, settlements and realized P&L by day, plus the shadow
  ledger's simulated summary kept separately in `data/summary.json`. The
  export uses the fills and settlements the bot copies into its journal on
  each live pass; while the bot is disarmed or stopped, later settlements
  appear only after its next live pass.
- **Public dashboard:** a "Spread maker / realized P&L" card (aggregate only)
  from the live P&L feed. After a release that changes the feed, restart it:
  `sudo systemctl restart market-maker-live-pnl.service`.
- **Standing and markouts** (measurement only, from 23 October): at the
  start of each live pass, before re-quoting, the bot notes whether another
  bid had got ahead of its resting quotes (outbid) or joined them; and it
  records how the price moved 10, 30 and 60 minutes after each fill, from
  the side bought. No extra requests. Both go to `measurements.jsonl`,
  summarised each pass in `measurements_summary.json`. `--status` prints
  the summary; the private export adds per-fill markouts and the summary.
  How the readings will be used is written in `RESEARCH_LOG.md`
  (2026-10-23), once, at the checkpoint.
- On the server: `--status`. Never mix live and shadow results.
