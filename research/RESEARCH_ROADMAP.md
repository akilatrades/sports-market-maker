# Sports Market-Making Research Roadmap

This is a research program, not a promise of profitability. Keep all strategy changes in research/paper mode until they pass pre-registered validation. No production order placement is enabled by this roadmap.

## Workstreams

### 0. Research integrity and data quality (blocking)
- Normalize timestamps to UTC and preserve source timestamps, ingestion timestamps, and source IDs.
- Freeze experiment parameters before validation; maintain a registry of variants and hypotheses.
- Use chronological splits and event/game-clustered uncertainty. Avoid random row splits and season leakage.
- Record attempted orders, non-fills, fills, partial fills, cancels, and rejected orders—not only filled trades.
- Deduplicate data, reconcile event settlement, and report missingness.
- Separate exploratory, training, validation, paper, and live datasets.

### 1. Execution simulator calibration
- Queue-ahead scenarios: 0, 1, 5, 10, 25, 50 contracts; treat public prints as incomplete evidence, not exact queue reconstruction.
- Partial fills and order persistence; cancel/replace latency; price movement while orders are pending.
- Fees, slippage, spread crossing, contract payout/settlement, and inventory financing/capital-hours.
- First-in-line, moderate-queue, and stress scenarios reported separately.
- Do not fit fill models on the same outcomes used to evaluate strategy P&L.

### 2. Quote-placement optimization
Test bid placement offsets and NO-side quote variants by market family, side, liquidity, and time-to-event. Optimize expected value per quote attempt—not just returns per fill. Include the opportunity cost of non-fills and inventory risk.

### 3. Toxicity and cancellation
Use only features timestamped before the order decision: sportsbook consensus changes, Kalshi price movement, stale-data age, liquidity changes, event state, and estimated adverse-selection risk. Compare cancel thresholds to a no-cancel baseline; quantify lost fill opportunity.

### 4. Cross-venue divergence / directional
Research synchronized Kalshi vs sportsbook/other venue consensus differences, with source latency and odds conversion/de-vig documented. Test both direction and market-making filters. Avoid using delayed or post-decision prices.

### 5. Market-family specialization
Maintain separate hypotheses and calibration by NBA/NFL/MLB/NHL, player props, game markets, time window, liquidity, and settlement rules. Pool only where diagnostics support pooling.

### 6. Probability model / ladder
For player props and ladders, compare calibrated distribution families and alternatives (Poisson, negative binomial, empirical residual, simulation, and hierarchical models where appropriate). Evaluate proper scoring rules and calibration, not only betting ROI.

### 7. Portfolio risk and bankroll
Limit event, player, team, sport, correlated market, and total inventory exposures. Stress correlated settlement outcomes, maximum loss, liquidity/exit assumptions, and payout concentration. Define risk budgets before any live test.

## Required experiment report
- Hypothesis, variant ID, parameters, and pre-registration timestamp
- Dataset window, split boundaries, data completeness, market-family coverage
- Number of games/events, attempts, non-fills, fills, partial fills
- Gross P&L, fees, slippage/haircut scenarios, net P&L, cents per contract, per attempt, capital-hours
- 1/5/15/30/60-minute markouts (where timestamps/quotes exist)
- Event-clustered confidence interval, chronological half results, and concentration
- Queue scenario sensitivity and assumptions
- Multiple-testing inventory; exploratory vs confirmatory status
- Decision: reject, continue exploratory, paper validation, or live pilot (approval required)

## Stage gates
1. Data quality: timestamp/ID reconciliation, source coverage, event mapping, settlement correctness.
2. Exploratory: discover candidate; no edge claim.
3. Confirmatory: frozen candidate on untouched chronological holdout; cluster-aware uncertainty.
4. Paper: real-time order lifecycle simulation and calibration; no real orders.
5. Live pilot: explicit human approval, smallest defined risk budget, kill switch, and ongoing monitoring.
6. Scale: only after repeatable net positive evidence, limits, and incident/rollback plan.

A positive point estimate is not sufficient. If the confidence interval includes zero, call it inconclusive; if an edge is fragile to queue or cost assumptions, reject or redesign.
