# NBA production readiness — separate from NFL

**Code-only. The NBA production timer is never enabled by this change.**
The current shared Kalshi balance and previous NFL pilot approval **do not**
authorize NBA production trading.

- A separate `live.prod_nba_auto` worker retains the bounded journal, one
  post-only NO order per scan, exchange reconciliation and emergency KILL guard.
- Dedicated private journal/state: `/home/trader/prod-nba-auto/`.
- Dedicated systemd unit and timer, disabled by default:
  `market-maker-prod-nba-auto.{service,timer}`.
- Dedicated root-only config: `/etc/market-maker-prod-nba-auto.env`.
  **Do not put production keys in GitHub, chat, or screenshots.**
- Explicit independent live flags: `KALSHI_ENV=prod`, `TRADE_MODE=live`,
  `PROD_NBA_AUTO_ARM=YES`, `ALLOW_PRODUCTION_TRADING=YES`,
  `DEMO_PILOT=0`, `TRADE_MARKET=nba`.
- Caps: **$3/order; $15 active; $30 per day; $50 lifetime nominal gross order
  costs with reserve**; $3/game, $3/team, 2 orders/game, 5 contracts/order;
  one new order per scan. These are *independent* of NFL's accounting.
  **Do not enable both production timers on the same funded account** without
  a tested shared-account risk manager and a separately authorized combined
  cap. Leave NFL stopped before any NBA money rollout.
- Frozen `no_seller_bookline` rule, 2–6h before NBA tipoff, post-only NO,
  original 1-cent quote improvement; the NFL extra-tick execution experiment
  **is explicitly disabled in this NBA baseline**. This cohort is separate.
- Must have `outputs/projections/latest.csv` AND a genuine
  `outputs/projections/latest_meta.json` with a timezone-aware
  `generated_utc` no more than 9h old. Never mistake git mtime for recency.
- Fresh NBA production quotes are read before the order and again right
  before submission; market must remain two-sided and unchanged.
- Current ESPN injury report must be readable; newer injury information
  and out statuses veto affected players or teams. Failure blocks orders.
- NBA sportsbook bookline veto is attached only for fresh quote rows with
  `updated_utc`; otherwise the rule uses the documented model fallback.
- A 2h30s real-clock cutoff is checked immediately before an order POST (the baseline requires at least 2h before tip).
- Distinct KILL file blocks entries and cancels owned resting NBA orders;
  already filled positions remain exposed until settlement.

## Operator verification — read only, do not arm

After checking out the code and installing requirements, the operator can
review public inputs without credentials:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader env KALSHI_ENV=prod TRADE_MODE=dry \
  .venv/bin/python -m live.prod_nba_auto --dry-run
```

Status (private journal counts only; no trading):

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo -u trader .venv/bin/python -m live.prod_nba_auto --status
```

Never enable the NBA timer or store production credentials without a **new,
explicit approval** after checking (1) true opening-night slate/projections,
(2) sportsbook freshness and credits, (3) actual NBA injuries/lineup safety,
(4) an empty Kalshi account with the NFL service disabled, (5) all risk tests,
and (6) a dry/no-order supervised end-to-end run.

NBA forward validation starts with its **first exchange-accepted NBA real
order**, not an NFL order. See `docs/FORWARD_VALIDATION.md`.
