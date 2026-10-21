# NFL + NBA simultaneously on one funded Kalshi account

**Status: active since 19–20 October 2026.** Code is released with
*Deploy funded worker code* and the bots are switched on or off with
*Go live / Stop funded bots* ([GO_LIVE_BUTTON.md](GO_LIVE_BUTTON.md)). The
console steps further down are the older manual path, kept for rebuilding
the server.

## What changed

NFL and NBA models keep independent tickers, candidate selection, NO-only
pricing, maker post-only execution, journals, cash checks, KILL switches and
individual per-game/contract limits. Both production workers already serialize
their entire live scan with a machine-local file lock,
`live.production_lock.account_lock`.

The new opt-in `live.shared_account_risk` reconstructs ownership of
BOTH journals and verifies all resting orders, held NO inventory and fills
against the **whole exchange account** before allowing a new order.
The worker then checks the per-sport budget AND these combined caps, while
the shared lock is held:

| Guard | Combined NFL + NBA | NFL | NBA |
|---|---:|---:|---:|
| Lifetime total of orders placed (never recycled) | **$1,050** | $50 | $1,000 |
| Orders placed per New York day | **$105** | $30 | $75 |
| Open orders at once (with 10% cushion) | **$90** | $15 | $75 |
| One order | — | $3 | $4 |
| Per game | — | $3 | $15 |
| Per team | — | $3 (lifetime) | $10 per day |
| Settled-loss stop | **$20 per day, $60 total** | (account-wide) | $20 / $60, plus account-wide |

Values come from `live/shared_account_risk.py`, `live/nfl_policy.py` and
`live/prod_nba_auto.py`; if this table and the code disagree, the code is
right.

Accepted, canceled, expired and settled submissions *all remain charged*
to lifetime and daily budgets. Active capacity is freed only on a
verified settlement, or when the original verified-expiry function finds
the order absent from resting, fill and held-position data **after the
game is over + 10 minutes**. Partial fills are not treated as zero risk.
An unknown order, manual position, conflicting dual owner, YES inventory,
unconfirmed POST or missing journal data prevents all new submissions.
The user may choose to reduce the combined caps later; no automatic
re-arming, payout assumptions or capital growth logic was added.

**Default behavior is unchanged.** Opt-in requires BOTH of:

- The production environment file for a worker contains
  `SMM_DUAL_MARKET=YES`
- The owner has created the root-owned marker
  `/etc/market-maker-shared-account.enabled`

If these are absent, the NBA legacy single-account gate continues
requiring NFL stopped; NFL also now checks whether NBA is stopped.
The old `deploy/activate_nba_auto.sh` is a single-sport handoff
and **must not be used for dual activation**.

## Switching on (current path)

Run **Go live / Stop funded bots → GO_LIVE** in GitHub. It stops both
timers, runs a signed account check, backs up the settings files, sets only
the two-sport opt-in flags and the NBA arm flag plus the root-owned marker,
repeats the account check and an NBA readiness check, then enables both
timers. A failure restores the files and leaves both timers off; any orders
already accepted before a failure stay live and must be checked in Kalshi.
Details: [GO_LIVE_BUTTON.md](GO_LIVE_BUTTON.md).

`deploy/activate_dual_market.sh` is the older console version of the same
steps. Do not use the single-market `activate_nba_auto.sh` for this.

## Manual console procedure (older path, for rebuilds)

Code releases now go through *Deploy funded worker code*; do not
`git pull` in the funded checkout while the bots are on.

## Step 1. Wait for green CI and schedule availability

Confirm GitHub Actions **tests** are green for both supported Python
versions. Verify both NFL and NBA sportsbook/model feeds are fresh for
their respective current entry windows. A model that is not eligible
should not place orders simply because its timer is enabled.

The existing research is not proof of an executable edge or income.
This makes it possible to *submit* qualifying orders from both sports;
it does not guarantee orders or fills.

## Step 2. Owner-safe code staging with both trading timers stopped

Do not update code while a one-shot trading service is actively
running. On DigitalOcean:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo systemctl stop market-maker-prod-nfl-auto.timer
sudo systemctl stop market-maker-prod-nba-auto.timer

systemctl is-active market-maker-prod-nfl-auto.service || true
systemctl is-active market-maker-prod-nba-auto.service || true
```

Proceed only after **both services** are inactive, and only if no
unknown RESTING orders, positions, or pending submission outcomes
require manual reconciliation. Stopping timers does not cancel or
settle already-accepted positions.

```bash
sudo -u trader git pull --ff-only origin main
sudo -u trader .venv/bin/python -m pytest -q \
  tests/test_shared_account_risk.py \
  tests/test_prod_nfl_auto.py \
  tests/test_prod_nba_auto.py
```

Preserve all original journal files and any existing KILL controls.
Both cohorts must have readable private journals; if a cohort has
never placed an order, create its blank journal **only if absent**,
with the owner account and permissions. Never overwrite a populated
journal. Do not bypass unreadable or uncertain journals.

## Step 3. Read-only signed account-wide verification

While both trading timers remain stopped, the owner can run:

```bash
cd /home/trader/sports-market-maker-prod-auto
sudo systemd-run --wait --pipe --collect \
  --uid=trader \
  -p WorkingDirectory=/home/trader/sports-market-maker-prod-auto \
  -p EnvironmentFile=/etc/market-maker-prod-auto.env \
  /home/trader/sports-market-maker-prod-auto/.venv/bin/python \
  -m tools.dual_account_preflight
```

Expected status is `SHARED_ACCOUNT_RECONCILED`. Inspect **both**
resting/held counts, the global caps and any historical NFL and NBA
journal submissions. A genuine blocker is evidence to stop, not a
reason to clear the journals. This report is GET-only and
credential-free in its printed output.

## Step 4. Explicit opt-in (owner decision; can submit real-money orders)

**Do not do this step solely to make an audit green.** Only after
full CI, signed reconciliation, and fresh eligibility checks, and only
if the owner authorizes active simultaneous real-money operation:

1. Back up the two root-owned production env files without exposing
   their contents in chat, logs or GitHub.
2. Add `SMM_DUAL_MARKET=YES` **once** to both
   `/etc/market-maker-prod-auto.env` and
   `/etc/market-maker-prod-nba-auto.env`. Keep original Kalshi keys
   and all existing trading caps/KILL controls unchanged.
   The NBA production env must additionally have
   `PROD_NBA_AUTO_ARM=YES` **only when the owner deliberately
   authorizes actual real-money NBA trading**; staging sets it to NO.
   NFL retains its existing `PROD_AUTO_ARM=YES` guard.
3. Create root-owned marker `/etc/market-maker-shared-account.enabled`
   with restrictive permissions; this represents the owner opt-in.
4. Run the **signed GET-only NBA preflight with --sync-inputs** using
   the NBA env file and check `ready=true`, `failures=[]`,
   and both cohorts' inventory. Verify the NFL live model is fresh too.
5. Enable the two existing timers with
   `systemctl enable --now market-maker-prod-nfl-auto.timer` and
   `systemctl enable --now market-maker-prod-nba-auto.timer`.

**These timers can submit live real-money orders** during their
individual market entry windows. Their executions serialize through
the same account lock, and their combined allowance is checked again
before admitting a new order. Their lifetimes and per-order caps
are not unlimited.

If either worker reports `Unowned`, `Unreconciled`, `unknown_outcome`
or `HALT`, stop BOTH timers immediately and inspect exchange and
journals with signed GET-only tools. Do not restart or override a
KILL file to force more activity.

## Risk and limitations

- **One machine only.** The existing shared lock is a local POSIX
  advisory file lock. Running another live writer on a different
  Droplet/container is not supported and defeats serialization.
- **One funded account only.** Do not manually trade over existing
  bot-owned contracts in the same series. Manual open positions and
  resting orders intentionally halt new entries rather than being
  silently incorporated into the risk model.
- **Do not clear historical attempts** to recycle the $1,050 lifetime allowance.
  There is no automatic monthly reset. This is still a bounded test.
- **No guarantee of profit.** An NBA in-sample backtest and one small
  losing NFL production cohort do not establish stable positive
  expectancy or revenue at a bigger size.
- Read-only Kalshi data can be delayed. If the state is ambiguous,
  the new system declines to submit a trade.
- The existing 24/7 funded-account **settlement P&L dashboard** is
  independent of these timers, and will keep distinguishing NFL
  and NBA realized outcomes.

## Rollback

Stop **both** timers, wait for running workers to finish, verify
account state, and return `SMM_DUAL_MARKET=NO` in BOTH env files
(or remove the option); remove the root-owned marker only after both
timers have stopped. Legacy isolated mode will then require a
one-sport-at-a-time handoff as before. Rollback **does not** cancel
or close outstanding inventory automatically.
