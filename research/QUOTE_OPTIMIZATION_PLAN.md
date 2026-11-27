# Execution Robustness & Quote Optimization — Preregistered Plan

Status: **plan only; no result claimed**. Keep all experiments separate from production and paper-ladder rules until independent validation.

## Track 1 — Execution robustness (implemented reporting tool)

Run `python -m research.execution_robustness` on archived `outputs/scan/orders_*.csv.gz`.

- Queue-ahead scenarios: 0, 1, 5, 10, 25, 50 contracts.
- Haircuts: 0, 0.5, 1, 2, 3, 4 cents per filled contract.
- Output by market family and side; fills, events, net cents, clustered t-stat, and chronological-half returns.
- Queue is explicitly a sensitivity proxy: public prints do not reveal queue position, cancellations, or exact partial fills.
- Use this tool to diagnose robustness only. The existing scan is hourly and its data cannot replay alternative quote prices or cancel decisions.

## Track 2 — Quote placement / toxicity cancellation (data capture required)

**Hypothesis:** NO liquidity provision can improve EV by selecting quote offsets and cancellation conditions based on spread, sportsbook divergence, quote freshness, market movement, and time-to-tip.

**Experimental design:** collect synchronized quote snapshots, sportsbook consensus, order-book depth/queue estimate, and public trade prints. Record each decision opportunity, including orders not placed, quote price, timestamp, order lifecycle, cancellations, fills, partial fills, and settlement.

Test fixed offsets/placements: at bid, +1, +2, +3 cents inside the spread; and quote at best bid vs one tick behind where applicable. Cancel rules: fair-value deterioration 1/2/3 cents; sportsbook move 1/2/3 points; stale sportsbook snapshot; Kalshi mid move against the quote 1/2/3 cents. Stratify by 6–4, 4–2, 2–1, and <1 hours pre-tip, spread, price band, and market family. Do not factorial-search all combinations; preregister a small primary comparison and label secondary cuts exploratory.

**Primary metric:** realized net P&L per filled contract, including actual maker fees; report opportunity EV per attempted order, fill probability, markouts at 1/5/15/30/60 minutes, P&L per capital-hour, and concentration by event.

**Pass bar:** at least 500 fills, 100 games, two chronological halves both positive, net mean >=1 cent/contract under queue-calibrated replay/live execution, and lower 95% game-clustered CI above zero. Live/paper outcomes remain separate. If lower CI is not above zero, label inconclusive, not pass.

**Kill criteria:** edge exists only under first-in-line; edge vanishes with 1+ contracts ahead; all profit concentrated in fewer than 10 games; cancellation improves markout but destroys net EV; or stale/misaligned sportsbook data drives results.

## Track 3 — Fresh independent validation cohort

Freeze a rule, commit hash, configuration, and pre-registered pass/kill criteria before collecting validation. No threshold changes mid-cohort. Capture every attempted order and cancellation. Review after two weeks for data integrity and execution diagnostics only; do not declare edge from a small two-week sample. Continue until the pass bar or a pre-registered stop condition is reached.

## Reporting conventions

- Report exploratory, in-sample, simulated, paper, and live results separately.
- Preserve all attempts, not only fills. Show fills and non-fills with conditional fill economics.
- Use game/event clustered confidence intervals and a date-block bootstrap sensitivity.
- For multiple comparisons, freeze one primary test; label all other cuts exploratory. Validate a selected rule on a chronological untouched cohort.
- The universal 2-cent haircut is not assumed valid for all families. The sensitivity report shows a range; actual live calibration by family/time/price/queue is a separate measurement.
