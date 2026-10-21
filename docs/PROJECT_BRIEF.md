# Sports Market Maker — project brief

**Python · prediction-market research · execution engineering · risk controls**

[Research dashboard](https://akilatrades.github.io/sports-market-maker/dashboard/) ·
[Source code](https://github.com/akilatrades/sports-market-maker) ·
[Experiment log](../RESEARCH_LOG.md) ·
[Forward-test rules](FORWARD_VALIDATION.md) ·
[Deep audit matrix](DEEP_AUDIT_MATRIX.md)

## The question

Can I post passive **NO** orders in NBA player-prop markets and earn a
positive return **after fees and actual exchange fills**? One-sided demand
for YES may create an opportunity, but a profitable backtest is not a
profitable executable strategy.

Despite the repository name, this is a **directional, one-sided
liquidity-provision strategy**, not a delta-neutral or continuous two-sided
market maker.

## How I approached it

1. **Start with probabilities.** Build NBA player-stat forecasts using
   expected playing time, rate estimates, matchup and availability context.
   Match each player, line, stat and game against the market.
2. **Test the trade, not just the forecast.** The original approach—buying
   the model's preferred outcome as a taker—lost money after execution
   costs. I then tested passive NO limit orders and sportsbook-price vetoes.
3. **Make the execution assumptions explicit.** Historical fills are inferred
   from public trade prints. Queue priority, trade-through capture, quote
   changes, selection bias, and some late-arriving model inputs can make
   the historical figures optimistic.
4. **Build bounded live infrastructure.** Signed Kalshi exchange access,
   post-only quotes, fee-aware pricing, order-intent journals, position/fill
   reconciliation, per-order and aggregate risk caps, isolated cohorts,
   kill switches, and a private read-only account view.
5. **Measure forward results separately.** Signed exchange fills,
   actual fees, settlement reconciliation, queue observations, and 5/15/60
   minute post-fill markouts are recorded separately from simulated P&L.

## Results — evidence tiers, not one blended equity curve

| Evidence | Observation | Important limit |
|---|---|---|
| Original taker-model test | Lost after spread and fees | Better forecasts do not automatically create executable trades |
| 2025–26 exploratory passive-NO replay | +1.65¢ per inferred fill without a model; +2.93¢ with a model veto | Selected in-sample; optimistic first-in-queue fill assumption |
| Smaller independent sportsbook comparisons | Approximately +3.4¢ to +4.0¢ per inferred contract | Game-clustered intervals touch or cross zero; not confirmatory |
| Signed NBA live audit, **21 Oct 2026 UTC** | 9 accepted orders, 1 fully filled maker order, 1 reconciled **positive** settled NBA market | Tiny, selected sample; **not** a fill-rate estimate, proven edge or income |

The first verified NBA fill occurred within 15 minutes of posting, in the
2–6-hour pre-tip entry window, with a positive estimated entry edge and
multiple sportsbook observations. The NO midpoint later moved favorably,
**but the executable NO bid did not improve** in the measured windows.
Its original journal expiry was more than two hours before tip; that
order came from an older or unknown strategy generation. Confirmed
starter status and independently projected minutes were not preserved
on that historical entry.

This is what we *know*, not an estimate of what all nine accepted orders
will eventually earn. The public dashboard's last published P&L can be
historical or stale; it is **not** a substitute for the signed private
exchange audit. Evidence:
[read-only audit 1](https://github.com/akilatrades/sports-market-maker/actions/runs/39541489414),
[audit 2](https://github.com/akilatrades/sports-market-maker/actions/runs/39542054076),
[execution review](NBA_OVERNIGHT_AUDIT_2026-10-21.md).

## Engineering decisions worth reviewing

| Concern | Where to inspect |
|---|---|
| Model generation, source freshness, and independent pregame context | [NBA projections](../live/nba_projections.py), [input verification](../live/nba_inputs.py), [pregame context](../live/nba_pregame_context.py) |
| How the strategy posts, verifies quotes, and cancels | [Production NBA worker](../live/prod_nba_auto.py), [Kalshi client](../kalshi/trading.py) |
| Ownership, fills, fees, and realized settlement | [Signed private audit](../live/order_opportunity_audit.py), [account reconciliation](../live/account_dashboard.py) |
| Shared-account risk isolation and kill conditions | [Shared risk](../live/shared_account_risk.py), [risk tests](../tests/test_shared_account_risk.py) |
| Hypotheses, negative results, and constraints on inference | [Research log](../RESEARCH_LOG.md), [NBA statistical audit](NBA_AND_MARKET_AUDIT_2026-10-18.md), [forward protocol](FORWARD_VALIDATION.md) |
| Automated CI and staged deployments | [Tests](../.github/workflows/tests.yml), [deployment workflow](../.github/workflows/droplet-release.yml) |

## What is still unproven

- **Profitability:** One settled NBA trade cannot identify a durable net
  edge. Orders still resting or unfilled are part of the denominator.
- **Queue and capacity:** Public prints are not guaranteed fills. Higher
  quote priority can cost price improvement and worsen adverse selection.
- **As-of validity:** Some historical inputs were unavailable at posting
  time. Live projected-minutes and confirmed-lineup source coverage still
  need prospective measurement.
- **Robustness:** A future cohort must hold rules fixed, track independent
  games, reconcile every order/settlement, and measure actual capital
  usage before any decision to increase size.

**Why it matters for trading roles:** the technical exercise is not simply
predicting NBA statistics. It connects pricing uncertainty to market
microstructure, live API execution, operational controls, and an honest
feedback loop from simulated fills to exchange-confirmed results.

*Research and software development used AI assistance; the repository
retains tests, experiment logs, and evidence sources for review.*
