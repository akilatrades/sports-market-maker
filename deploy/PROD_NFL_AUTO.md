# NFL production worker

**Status: live.** The funded NFL bot (`live/prod_nfl_auto.py`, strategy
version `nfl-no-v3-baseline-quote`) shares one Kalshi account with the NBA
bot. Switch it on or off only with the owner-only
[Go live / Stop button](GO_LIVE_BUTTON.md); release code with *Deploy funded
worker code*. The installation and first-arming steps further down are the
original setup, kept for rebuilding the server.

## Defined experiment, not a profitable product

- Funded account: **$250**, shared with the NBA bot.
- **Hard cumulative gross-cost budget: $50**, including 10% worst-case fee reserve
  on valid 10c–90c prices. This is an *ever-decreasing* lifetime budget; proceeds
  are not recycled until a separate researched rollout is approved.
- Max **$3 order**, **5 contracts** per order, **$15 active exposure**, **$30 daily
  spend**, **$3/game**, **$3/team** (lifetime), **2 orders/game** and one new order per scan.
- There is no NFL-only loss stop. The account-wide stops apply: new orders stop
  for the day after $20 of settled NBA + NFL losses and for good after $60
  (`live/shared_account_risk.py`).
- Sizing reduces contract quantity until the cost **including the reserve**
  fits all remaining caps. Example: a 60-cent quote uses four contracts ($2.40
  cost, $2.64 reserved), because five would exceed the $3 game/team allowance.
- Post-only NO strategy, standard `no_seller_bookline` book/model veto.
- Orders 10–120 minutes pregame, always 1¢ better than the best NO bid when the
  spread allows (no second cent of improvement), expiring at the scheduled kickoff.
- Fresh real production quote checked just before POST, fail if changed or if more competitive quote would cross the other side. All orders remain post-only. This is a forward experiment, not a validated fill-rate improvement.
- One-cent spreads cannot be improved while remaining a passive maker, so they retain the original quote and queue position.
- Model edge above 15 cents is treated as potentially mismatched/stale
  and *not auto-executed*. No profitability guarantee.
- Private **write-ahead order journal** (outside repo) ensures network timeouts
  never silently become duplicate placements. Unknown orders/positions prevent
  new orders.
- The bot releases active capacity for expired unfilled orders only after a 10-minute grace period, confirming no resting order, fill, or held position. All attempted gross costs still consume the $50 lifetime ceiling.
- Server polls Kalshi for fill IDs, prices, order queue, fees, and settlements;
  durable private events are saved for later forward evaluation.
- Queue position is observed on each completed pass for owned resting orders.
  `last_scan.json` in the private state directory records the last scan time,
  entry-filter counts, acceptance, and named blocking reasons. `--status`
  displays that saved observation; it is not a fresh exchange-account query.
- Settlement records normalize current dollar cost fields and legacy cent cost
  fields, with fees in dollars. Missing costs or fees produce unknown P&L.
  Older journal records receive append-only corrections after reconciliation.
- Current roster/injury verification failures cancel affected owned resting
  orders; quote or data errors refuse new orders.
- Only the account owner can arm a production timer, and they can always stop it.

## Safe installation: separate from Demo

Install a brand-new checkout under
`/home/trader/sports-market-maker-prod-auto`; do **not** edit or repurpose
`/home/trader/sports-market-maker`, `/etc/market-maker.env` or
`market-maker.timer`.

After this change has been merged and its Python tests pass, the owner can use:

```bash
curl -fsSL https://raw.githubusercontent.com/akilatrades/sports-market-maker/main/deploy/install_prod_auto.sh | sudo bash
```

This does NOT create production credentials, start trading or enable the timer.
It runs a public-data-only dry scan first. A dry candidate is not an actual
accepted order, nor evidence of profitability.

## Before real-money automation

1. The account owner must verify $250 *available in Kalshi Production* and
   independently create **production API credentials**. Demo keys are different.
   Never share keys in chat or support tools, or publish/commit them to GitHub.
2. Ensure Kalshi Production has **no manual resting orders or open positions**.
   The account is shared only with the NBA bot (see
   [DUAL_MARKET_PRODUCTION.md](DUAL_MARKET_PRODUCTION.md)); anything else halts new orders.
3. Root-only `/etc/market-maker-prod-auto.env` (permissions 0600) must include
   these names and **the actual production key material**:
   ```ini
   KALSHI_ENV=prod
   TRADE_MODE=live
   PROD_AUTO_ARM=YES
   ALLOW_PRODUCTION_TRADING=YES
   DEMO_PILOT=0
   TRADE_MARKET=nfl
   KALSHI_KEY_ID=...use-your-production-id...
   KALSHI_PRIVATE_KEY=...use-your-production-private-key...
   ```
   The placeholder values above are NOT valid credentials.
4. Confirm the read-only dry scan, current verified roster, injury feed,
   market ticker, price, *net expected edge*, and correct cap in logs.
5. Enable only after explicit confirmation; automation will send real-money
   orders as opportunities arise. Today this is done with **Go live / Stop →
   GO_LIVE**; the original manual commands were:
   ```bash
   sudo systemctl enable --now market-maker-prod-nfl-auto.timer
   sudo systemctl list-timers market-maker-prod-nfl-auto.timer --no-pager
   sudo journalctl -u market-maker-prod-nfl-auto.service -n 35 --no-pager
   ```
6. Audit Kalshi Production orders after the first exchange-confirmed acceptance.
   No automatic stake expansion or additional capital authorization is coded.

## Emergency stop — do not delete the journal or KILL file to re-arm

Preferred: **Go live / Stop → STOP_AND_CANCEL** in GitHub, which stops both
bots and cancels their resting orders ([GO_LIVE_BUTTON.md](GO_LIVE_BUTTON.md)).
Console fallback: create the permanent stop marker (blocks all future
production orders), disable the timer, and run one final pass to cancel
**owned** resting orders:

```bash
sudo -u trader touch /home/trader/prod-nfl-auto/KILL
sudo systemctl disable --now market-maker-prod-nfl-auto.timer
sudo systemctl start market-maker-prod-nfl-auto.service
sudo journalctl -u market-maker-prod-nfl-auto.service -n 35 --no-pager
```

If the cancellation request fails, check the Kalshi website and cancel manually.
A filled position is still exposed to settlement even after resting orders are
canceled. A service exit does **not** guarantee a cancellation or loss limit.

For latest private counters without credentials or exchange writes:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader .venv/bin/python -m live.prod_nfl_auto --status
```

## Operational limitations

- This is not a $250 trading authorization. Full $250 balance stays available
  but only $50 in **cumulative order cost plus fee reserve** is permitted.
- The software gross spend ceiling is not a brokerage account guarantee and
  cannot prevent losses from orders made outside the pilot.
- The first production fills do not prove edge; the 2025-26 backtests are
  exploratory, and NFL profitability has not yet been independently validated.
- Automated model updates and sportsbook data refresh use repository snapshots;
  review freshness before any first live start.
- We do not promise any particular kickoff entry, order acceptance, fill,
  positive P&L, or automatic continued trading after the budget is exhausted.

