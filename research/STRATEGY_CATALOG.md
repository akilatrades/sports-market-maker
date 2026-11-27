# Candidate Strategy Catalog (Hypotheses, Not Claims)

Rank is a research-priority ordering, not a profitability ranking.

| Priority | Hypothesis | Signal / setup | Main risk | First test |
|---|---|---|---|---|
| 1 | Quote placement + fill-quality optimization | Placement offset, queue estimate, time-to-event, liquidity | Queue/latency model error | Quote-attempt EV and net fill outcomes by offset |
| 2 | Toxicity-aware cancel/avoid | Pre-decision sportsbook move, Kalshi move, stale-data age | Cancels too late or remove good fills | Markout and opportunity EV vs baseline |
| 3 | Cross-venue divergence | Synchronized, de-vigged sportsbook/venue consensus vs Kalshi | Odds conversion, stale quotes, latency | CLV/markout after source latency adjustment |
| 4 | Time-window liquidity specialization | Distinct pregame windows and market families | Selection bias, limited samples | Attempts/fill rate/net EV by time window |
| 5 | NO-side and asymmetric spread | Different risk/price response on YES/NO | Binary-market pricing/settlement nuance | Side-stratified, calibrated, holdout results |
| 6 | Inventory/correlation controls | Exposure across teams, players, events, related markets | Correlation estimates unstable | Simulated portfolio risk reduction vs EV loss |
| 7 | Player-prop ladder distribution | Calibrated tail and discrete distribution | Model misspecification | Brier/log loss, calibration, holdout ROI |
| 8 | Forecast revision (weather, injuries, lineup) | New information vs market adjustment | News timestamp, stale inputs | Event-time study with strict as-of data |
| 9 | Price discovery / lag | Venue leads another venue | Non-synchronous quotes, limits | Timestamp alignment, lead-lag test, costs |
| 10 | Incentive/fee-aware quoting | Incentives and fee schedule alter economics | Incentives change, volume constraints | Marginal net EV including eligibility/rules |

## Research principles
- Treat every row as a falsifiable hypothesis.
- Never count a fill as evidence of value without markout/settlement and fees.
- Include no-fill opportunity costs; evaluate per quote attempt.
- Avoid variant fishing: maintain an experiment registry, correct for multiple testing, and freeze finalists.
- Start with market families where data quality, liquidity, and settlement mapping are strong.
