# Supervised NFL production pilot — Oct 18, 2026

**Do not treat merging code as authorization to send money. This is a one-shot operator action, NOT an unattended bot.** No real orders have been placed by this change.

## Design

- Independent production checkout at `/home/trader/sports-market-maker-prod`, never touch the running Demo checkout/service.
- Production-only API key from a separately created production account credential, loaded by a **different** systemd `EnvironmentFile`; NEVER copy Demo keys.
- Dry run reads **production public quotes**, without trading credentials or trading writes.
- Live mode needs `--live` and `KALSHI_ENV=prod`, `TRADE_MODE=live`, `PROD_PILOT_ARM=YES`, `ALLOW_PRODUCTION_TRADING=YES`. Post-only NO, current sportsbook veto, 30–120 minute kickoff window.
- Maximum **$2 committed per order**, **ONE** submission attempt total, **$5 open** design ceiling, **$25** declared experiment ceiling. Since it stops after the first attempt, no re-arming or extra exposure until manual review.
- Rejects pre-existing resting production orders or production positions. Fails closed on missing balance/credentials and suspicious kickoff, roster or stale model inputs.
- Fsync'd private intent journal `/home/trader/prod-nfl-pilot/orders.jsonl` written **before** placing anything. Network timeouts lock out retries. Never delete the journal to bypass this lock. Logs stay outside Git.
- It **cannot guarantee a fill or a loss stop**. One $2 order may be accepted and remain unfilled; review queue/fills/settlement in Kalshi. Any live order can lose its full cost plus fees. Cancel manually in Kalshi if needed.

## Prerequisites (human operator)

1. Explicit user approval for one actual production order, and at least $25 *available on Kalshi production*. Confirm production API trading privileges and that the operator can cancel an order in Kalshi.
2. Production API key pair stored only in `/etc/market-maker-prod.env` (root-owned, mode 0600). Do NOT show this file, send it in chat, or commit it.
3. Merge the PR only after both Python-version tests pass. Run read-only dry first; inspect candidate, price and kickoff manually. Skip entirely if no eligible market.
4. Run live service **once** and inspect the exchange immediately. NEVER add a timer or restart policy.
5. Independent manual audit of accepted order, possible fill and settlement BEFORE any additional real-money pilot.

## Separate server setup

These commands are *operator instructions*, not execution that occurred:

```bash
sudo -u trader git clone --depth 1 https://github.com/akilatrades/sports-market-maker.git /home/trader/sports-market-maker-prod
sudo -u trader python3 -m venv /home/trader/sports-market-maker-prod/.venv
sudo -u trader /home/trader/sports-market-maker-prod/.venv/bin/pip install -r /home/trader/sports-market-maker-prod/requirements.txt
sudo cp /home/trader/sports-market-maker-prod/deploy/market-maker-prod-nfl*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start market-maker-prod-nfl-dry.service
sudo journalctl -u market-maker-prod-nfl-dry.service -n 30 --no-pager
```

Only after dry checks pass and the user has authorized the first real order, create `/etc/market-maker-prod.env` **locally** with production credentials and the four named safety flags. Use a root-owned 0600 file. Never print the secrets. The user must personally start the one-shot unit:

```bash
sudo systemctl start market-maker-prod-nfl.service
sudo journalctl -u market-maker-prod-nfl.service -n 30 --no-pager
```

Afterwards check Kalshi Production **Orders** and **Positions**; never infer an actual fill from a `placed` response. Do not rerun live. This first pilot deliberately has no rearm command.

## What this is not

- Not a strategy with demonstrated positive forward NFL expectancy.
- Not a $25 loss-limit controller for an entire account or other orders.
- Not proof that the Demo limit order is fillable; production is a different order book.
- Not a replacement for studying 2–6h vs 0.5–2h timing; the original 2–6h rule is unchanged.
