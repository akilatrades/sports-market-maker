# Spread maker pilot (third bot)

`live/prod_spread_auto.py`, strategy version `spread-maker-v1`. It posts a
small buy order on **both sides** of markets where the gap between the best
bid and the best offer (the *spread*) is 8¢ or more, one cent better than
anyone else on each side. When both orders fill, the bot owns a YES and a NO
contract that together pay exactly $1 and cost less than $1: a locked profit.
When only one fills, it holds that contract to settlement.

Plan and pass/fail bars: `RESEARCH_LOG.md`, "2026-10-22: Spread maker pilot,
shadow and small live (plan)" and its implementation notes. The evidence is a
**simulated, in-sample** backtest (strategy sweep, family 7). The pilot exists
to find out whether real fills look like the simulated ones; it is not a
profit forecast.

## What it does

- **Markets:** the 64 series in `live/spread_policy.py` (esports, smaller
  basketball and hockey leagues, cricket, soccer side markets, UFC, motor
  racing and others). Never an NBA or NFL player prop and never a market
  another bot holds. Series that pay a maker fee are skipped.
- **When:** markets whose expected expiration is 4 to 7 hours away.
- **Quote:** YES bid at best YES bid + 1¢, NO bid at best NO bid + 1¢, one
  contract each, post-only (never takes liquidity), expiring on the exchange
  after 65 minutes. Prices come from the public order book with the bot's own
  orders removed, so it never prices off itself.
- **Inventory:** once it holds one contract on a side of a market, it stops
  quoting that side there.
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
| Contracts per order | 1 | |
| Net contracts per market and side | 1 | |
| Open exposure (resting orders + held contracts, at cost) | $25 | |
| Orders per pass / per New York day | 20 / 300 | Cancelled orders still count |
| Own realized-loss stop, per day / total | −$5 / −$15 | Cancels its quotes and stops |
| Account realized-loss stop, per day / total | −$20 / −$60 | Shared with NBA and NFL |

- The NBA and NFL caps ($165 open, $180 a day, $2,050 lifetime) are
  unchanged and do not include spread orders. All three bots together can
  have at most $190 open.
- The account stops count settled markets of all three bots, so spread
  losses can stop NBA and NFL for the day, and the reverse.
- Worst plausible case: the $15 own stop is reached and every open position
  then loses: about $15 + $25 = $40.

## Safety rules (same as the other bots)

- Every order and cancel is written to the journal
  (`/home/trader/prod-spread-auto/journal.jsonl`) before it is sent.
- A placement the exchange refuses with an HTTP 4xx (for example a post-only
  order that would have crossed) is recorded as refused only after a signed
  read shows no such order. **Any other failure halts all three bots** until
  the owner reconciles it, exactly as for NBA and NFL.
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

## Switching off

| Command | Effect |
|---|---|
| `--disarm` | No new orders. Resting quotes expire within 65 minutes. Shadow keeps running. |
| `--cancel` | Cancels the bot's resting orders now and leaves a `KILL` file, so every pass only cancels. `--resume` removes it. |
| `--off` | `--disarm` + `--cancel`, then stops the timer (shadow stops too). |

The **Go live / Stop funded bots** workflow controls the NBA and NFL bots
only; it does not stop the spread bot. Use this script for the spread bot.
The account loss stops do apply to all three.

## Not yet included

- The private fills export and the public P&L page cover NBA and NFL only.
  Until a follow-up adds the spread bot, its live results are on the server
  (`--status`). Never mix them with the shadow ledger or with replays.
