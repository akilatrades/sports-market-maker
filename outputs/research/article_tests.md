# Market-making ideas on the 2025-26 replay (simulated, in-sample)

Plan: RESEARCH_LOG.md, 2026-10-21. One contract per order, v5-like caps,
fills as if first in line (flow share 1.0) and with a quarter of the
trading reaching us (0.25, 10 draws). ✅/❌ = the plan's pass bar.

## 1. Where the profit per filled contract comes from (cents)

| Flow share | Filled | ¢ per contract | Entry edge | Model error (unfilled) | Adverse selection (filled − unfilled) | t | Design effect | Within-game corr. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.0 | 14,478 | +3.32 | +6.40 | -5.10 | +2.02 | 2.96 | 2.18 | 0.059 |
| 0.25 | 13,726 | +3.31 | +6.42 | -4.90 | +1.79 | 2.66 | 2.15 | 0.060 |

All 53,549 replay orders, no caps: adverse selection +2.35¢ (t 4.87).

## 2. Minimum edge

| Variant | flow share | fills | cents_per_contract | t | pnl | pnl_h1 | pnl_h2 | max_drawdown |
|---|---|---|---|---|---|---|---|---|
| min edge 0c | 1.0 | 14,478 | 3.32 | 6.10 | 481.04 | 186.19 | 294.85 | -23.25 |
| min edge 0c | 0.25 | 13,726 | 3.31 | 5.94 | 453.84 | 174.03 | 279.81 | -24.31 |
| min edge 1c ❌ | 1.0 | 13,665 | 3.45 | 6.22 | 471.50 | 178.67 | 292.83 | -20.72 |
| min edge 1c | 0.25 | 12,961 | 3.45 | 6.08 | 447.12 | 167.65 | 279.47 | -23.21 |
| min edge 2c ❌ | 1.0 | 12,651 | 3.51 | 6.09 | 444.53 | 161.21 | 283.32 | -23.65 |
| min edge 2c | 0.25 | 12,004 | 3.54 | 6.01 | 424.48 | 151.49 | 273.00 | -25.83 |
| min edge 3c ❌ | 1.0 | 11,435 | 3.61 | 5.94 | 412.63 | 134.83 | 277.80 | -23.02 |
| min edge 3c | 0.25 | 10,847 | 3.67 | 5.91 | 398.36 | 126.54 | 271.83 | -24.50 |
| min edge 4c ❌ | 1.0 | 10,144 | 3.69 | 5.76 | 374.75 | 120.07 | 254.68 | -26.59 |
| min edge 4c | 0.25 | 9,629 | 3.78 | 5.77 | 364.29 | 114.28 | 250.00 | -27.29 |

## 3. Posting time

| Variant | flow share | orders | fills | cents_per_contract | t | pnl | pnl_h1 | pnl_h2 |
|---|---|---|---|---|---|---|---|---|
| posted 5h, 0c (control) | 1.0 | 22,158 | 13,682 | 3.15 | 5.58 | 431.41 | 180.56 | 250.85 |
| posted 5h, 0c (control) | 0.25 | 22,158 | 12,976 | 3.18 | 5.50 | 412.34 | 172.58 | 239.76 |
| posted 2h, +0c per hour beyond 2h ❌ | 1.0 | 23,639 | 13,165 | 3.27 | 5.67 | 430.52 | 163.25 | 267.27 |
| posted 2h, +0c per hour beyond 2h | 0.25 | 23,639 | 12,489 | 3.27 | 5.58 | 408.35 | 151.41 | 256.94 |
| posted 4h, +0c per hour beyond 2h ❌ | 1.0 | 22,841 | 13,912 | 3.33 | 5.97 | 462.86 | 176.47 | 286.39 |
| posted 4h, +0c per hour beyond 2h | 0.25 | 22,841 | 13,194 | 3.28 | 5.75 | 433.12 | 167.27 | 265.85 |
| posted 4h, +0.5c per hour beyond 2h ❌ | 1.0 | 21,478 | 13,079 | 3.38 | 5.85 | 442.42 | 162.91 | 279.51 |
| posted 4h, +0.5c per hour beyond 2h | 0.25 | 21,478 | 12,412 | 3.36 | 5.66 | 416.78 | 154.56 | 262.22 |
| posted 6h, +0c per hour beyond 2h ❌ | 1.0 | 20,511 | 12,887 | 2.29 | 3.88 | 294.87 | 179.06 | 115.81 |
| posted 6h, +0c per hour beyond 2h | 0.25 | 20,511 | 12,236 | 2.34 | 3.91 | 286.27 | 174.41 | 111.86 |
| posted 6h, +0.5c per hour beyond 2h ❌ | 1.0 | 17,883 | 11,147 | 2.37 | 3.79 | 263.73 | 142.97 | 120.76 |
| posted 6h, +0.5c per hour beyond 2h | 0.25 | 17,883 | 10,592 | 2.43 | 3.82 | 256.93 | 138.33 | 118.59 |

## 4. Same-game inventory penalty

| Variant | flow share | fills | pnl | sharpe | sharpe_h1 | sharpe_h2 | worst_night | max_drawdown |
|---|---|---|---|---|---|---|---|---|
| penalty 0c per order already in the game | 1.0 | 14,478 | 481.04 | 0.48 | 0.46 | 0.50 | -12.30 | -23.25 |
| penalty 0c per order already in the game | 0.25 | 13,726 | 453.84 | 0.47 | 0.45 | 0.49 | -12.76 | -24.31 |
| penalty 0.1c per order already in the game ❌ | 1.0 | 12,350 | 458.00 | 0.48 | 0.43 | 0.52 | -14.18 | -21.32 |
| penalty 0.1c per order already in the game | 0.25 | 11,706 | 438.75 | 0.47 | 0.42 | 0.51 | -14.15 | -23.08 |
| penalty 0.25c per order already in the game ❌ | 1.0 | 9,159 | 355.12 | 0.44 | 0.38 | 0.48 | -11.69 | -22.05 |
| penalty 0.25c per order already in the game | 0.25 | 8,694 | 345.42 | 0.43 | 0.37 | 0.48 | -11.88 | -21.99 |
| penalty 0.5c per order already in the game ❌ | 1.0 | 6,522 | 249.98 | 0.37 | 0.26 | 0.47 | -6.82 | -14.16 |
| penalty 0.5c per order already in the game | 0.25 | 6,202 | 245.44 | 0.38 | 0.26 | 0.46 | -7.00 | -13.67 |

## 5. Quote choice by P(fill) × edge (second half only)

| Flow share | Orders | Choice ¢/100 orders | Control ¢/100 | Difference | t | Chosen |
|---|---:|---:|---:|---:|---:|---|
| 1.0 | 22,135 | +173.9 | +185.7 | -11.8 | -2.68 | {'improve1': 0.669, 'join': 0.287, 'improve2': 0.043} |
| 0.25 | 22,135 | +162.4 | +177.0 | -14.6 | -3.39 | {'improve1': 0.656, 'join': 0.287, 'improve2': 0.057} |

Passes: ❌
