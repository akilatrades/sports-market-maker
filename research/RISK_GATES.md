# Research and Paper-Trading Risk Gates

This file is a policy checklist. It does not configure or activate the production bot.

## Before any paper candidate
- [ ] Data and event/market mapping quality audited
- [ ] Timestamp alignment and source latency documented
- [ ] Experiment parameters frozen and registered
- [ ] Attempts and non-fills included in denominator
- [ ] Fee and slippage sensitivity computed
- [ ] Queue model calibration/sensitivity shown
- [ ] Event-cluster uncertainty and chronological splits
- [ ] Variant count and multiple testing disclosed

## Paper candidate minimums (guidelines, not proof)
- At least 500 fills and 100 distinct games/events, where feasible for the strategy
- Positive results in both chronological halves
- Net expectancy >= 1 cent/contract under a defensible execution scenario
- Lower 95% game/event-clustered confidence bound above zero for an edge claim
- No single event or tiny group dominates the result
- Results survive queue ahead, fees, slippage, latency, and adverse-selection stress
- Reconciled fill and settlement ledger

If any minimum is not reached, state “insufficient evidence” or “inconclusive,” not “profitable.”

## Live pilot prerequisites (requires explicit approval)
- Written strategy version, market scope, and risk budget
- Max position per market/event/player/team/sport and portfolio
- Max daily loss, max outstanding orders, max notional/capital
- Kill switch tested and reachable; automatic stale-feed shutdown
- Order/position reconciliation and alerting
- Monitoring for fill quality, markouts, drift, errors, and outages
- Rollback to last safe version; no automatic scale-up
- Human approval for live activation and any budget increase
