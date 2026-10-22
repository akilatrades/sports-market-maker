# Ladder maker checks (exploratory)

## 1. 2025-26 replay, rungs without a two-book line, by slice (simulated, in-sample)

Negative-binomial ladder against the current rule (two-book line, else the
stat model) on the same rungs; one contract, first in line, no caps.

### stat

| Bin | Rungs | Ladder fills | Ladder ¢ (t) | Current rule fills | Current rule ¢ (t) |
|---|---:|---:|---:|---:|---:|
| assists | 929 | 217 | +2.91 (1.05) | 244 | +1.93 (0.69) |
| points | 1,642 | 436 | +4.14 (1.80) | 652 | +2.39 (1.24) |
| rebounds | 1,222 | 265 | +5.79 (2.04) | 324 | +3.68 (1.38) |
| threes | 885 | 265 | +5.51 (1.95) | 348 | +0.95 (0.38) |

### book lines for player and stat

| Bin | Rungs | Ladder fills | Ladder ¢ (t) | Current rule fills | Current rule ¢ (t) |
|---|---:|---:|---:|---:|---:|
| 1 | 390 | 127 | +13.90 (4.10) | 99 | +7.75 (1.98) |
| 2 | 608 | 141 | +1.23 (0.30) | 171 | -2.13 (-0.55) |
| 3+ | 3,680 | 915 | +3.82 (2.41) | 1,298 | +2.43 (1.69) |

### spread at posting

| Bin | Rungs | Ladder fills | Ladder ¢ (t) | Current rule fills | Current rule ¢ (t) |
|---|---:|---:|---:|---:|---:|
| 1¢ | 720 | 95 | +4.37 (1.09) | 172 | +2.40 (0.68) |
| 2¢+ | 3,958 | 1,088 | +4.61 (2.95) | 1,396 | +2.25 (1.60) |

### distance from nearest book line

| Bin | Rungs | Ladder fills | Ladder ¢ (t) | Current rule fills | Current rule ¢ (t) |
|---|---:|---:|---:|---:|---:|
| 0 (one-book line) | 1,987 | 640 | +3.09 (1.61) | 817 | +1.71 (0.94) |
| 1-3 | 2,192 | 487 | +6.78 (4.00) | 608 | +2.98 (1.82) |
| more than 3 | 499 | 56 | +2.68 (0.46) | 143 | +2.37 (0.73) |

## 2. This season's feed (public snapshots, 2-6 hours before tip)

Nights: 2026-10-20, 2026-10-21. Sportsbook lines per player and stat in a snapshot: median 2, mean 3.5; 44% have 3 or more (the feed already includes alternate lines).

Of 1,113 Kalshi rungs: 177 have a two-book line (v5's universe), 884 would get a ladder price without one, 52 have no book line for the player and stat. Spread of 2¢ or more: 34% of two-book rungs, 76% of ladder-only rungs.

## 3. Pipeline check on this season (not evidence: two nights)

865 ladder-only rungs with results in 7 games (2026-10-20, 2026-10-21). Log loss: ladder 0.4296, stat model 0.4720, Kalshi mid 0.4264.

Paper orders (edge 0-15¢, NO 5-95¢, first in line): ladder 229 orders, 101 fills, $+2.41; stat model 470 orders, 256 fills, $+8.86. Simulated.
