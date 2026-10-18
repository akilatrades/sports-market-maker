# Execution readiness snapshot — October 17, 2026

This is an evidence checklist, **not** permission to run real-money trades or an instruction to enable the VPS timer.

## Currently observable

- The historical NBA resting-NO rule was estimated at **+2.93 cents per simulated filled contract** after modeled fees. It has **no validated 2026–27 real-fill expectancy** yet.
- The Kalshi Demo account was manually verified at **$2,500 available** on October 17. This is historical verification, not a balance feed.
- The V2 Demo order/cancel test proved only one manual order's acceptance and cancel; **zero fills** in that test. Candidate selection, queue capture, full loop and settlements remained untested.
- The VPS timer was previously stopped during V2 testing. This repository **cannot establish whether it is currently running**, and no publicly committed account ledgers establish confirmed forward P&L.
- GitHub research dry runs use **public production quotes**, `TRADE_MODE=dry`, no trading secrets and a separate **$250 research sizing reference**. They **do not** reflect the Demo account's current balance or place orders.
- On October 17 the GitHub NBA dry-run failed because its production data host differed by hostname from the default Demo execution client. The code now recognizes documented production host aliases, while refusing any cross-Demo/production pairing; scheduled research workflows explicitly set `KALSHI_ENV=prod` and keep `TRADE_MODE=dry`.
- Separate $500 paper ledgers had **187 simulated settled fill rows**, combined **−$93.65**. This sum is not one deployed portfolio. Individual experiment results can be misleading: La Liga's +$19.23 arose from **five independent matches**.
- Polymarket US is strictly read-only research. The league-tagged PROP-filtered API initially returned zero NFL/NBA rows; this is **not** evidence that no props exist. A bounded unfiltered first-page diagnostic now shows the gap without promoting it into an opportunity.

## Read-only VPS verification (to be run by the operator)

Never print, commit, or paste `/etc/market-maker.env`, API keys, or private customer/account records.

1. Verify the timer and service independently on DigitalOcean: `sudo systemctl is-active market-maker.timer` and `sudo systemctl status market-maker.service --no-pager`. These commands do not start anything.
2. Check just the nonsecret mode flags: `sudo awk -F= '/^(KALSHI_ENV|TRADE_MODE|DEMO_PILOT)=/{print $1 "=" $2}' /etc/market-maker.env`. Expect `KALSHI_ENV=demo`; verify `TRADE_MODE` before any order-capable execution. Do not make blanket configuration changes.
3. Inspect private `outputs/live/last_run.json` / `outputs/live/nfl/last_run.json`, client error logs, order IDs, fill IDs, open positions, and cancel/rejection reasons locally. Resolve missing report files as **unknown**, not as zeros.
4. Preserve a safe backup of private ledgers before any deployment; reconcile orders/fills against Kalshi Demo directly and do not publish account credentials or personal identifiers.
5. Confirm the kill switch, $2 per order, $10 committed exposure, daily loss stop, one new order per run and timer/48-hour pilot behavior in the actual deployed revision. GitHub's generic `RiskLimits` defaults **are not** the pilot caps.
6. Run one manual `TRADE_MODE=dry` pass in the correct Demo venue, then one supervised Demo-only pass **only after** verifying correct candidate matching, cancel routes, no duplicate orders and account reconciliation. Demo mode still changes exchange state; do not infer permission to submit from a GitHub merge.
7. Keep any market's real-money deployment disabled until actual fill capture and independently clustered post-fee settlements justify it.

## Frozen validation decision rule

From the first exchange-accepted actual strategy order, measure **30 calendar days AND 500 uniquely settled exchange BUY fill records**, with sufficient matured trade volume and realized settlement completeness (both at least 95%). Report queue rank, fill capture, partial fills, net dollars, per-contract return, return per placed order including zeros, and event/game clustered uncertainty. If comparable capture is below 25%, revisit scaling assumptions. These thresholds trigger review, never automatic bankroll increases. See [forward protocol](FORWARD_VALIDATION.md).

## What would change the answer

**No profits can be called realized from this dashboard until the server provides timestamped, reconciled exchange order/fill/settlement evidence.** Historical simulations, eligible market count and manual V2 order acceptance cannot establish an edge. The next NBA season observation starts no earlier than actual accepted orders around the October 20 NBA opener; a scheduled workflow alone does not start the clock.
