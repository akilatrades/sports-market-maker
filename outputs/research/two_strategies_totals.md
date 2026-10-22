# NBA game totals (KXNBATOTAL): proposed totals maker (exploratory, simulated)

Kalshi quotes: the archived scan's hourly NO quotes 1-4.5 hours before tip,
each resting one hour, fills from public trade prints as if first in line.
Fair value from ESPN's game total (one number per game, probably near the
close: **an upper bound**, see RESEARCH_LOG) and the residual distribution
fitted on 6,442 games from 2020-21 to 2024-25 (mean +0.36, sd 17.92 points; 2025-26: +0.50, 18.22).

## The archived scan, re-scored (every hourly NO row as its own order)

1,671 fills in 620 games: no fee +0.74¢ (t 0.36); 1¢ fee -0.26¢ (t -0.12); the scan's own fee +0.37¢.

## Calibration at each market's first quote (log loss, lower is better)

1,077 markets, 776 games.

| Source | Log loss | minus Kalshi mid (t) |
|---|---:|---:|
| Kalshi mid | 0.6151 | |
| ESPN line, normal | 0.6116 | -0.0034 (-1.64) |
| ESPN line, empirical | 0.6118 | -0.0032 (-1.50) |

## Replay: one contract per market, edge 0-15¢, NO 5-95¢

| Flow, fee | Fair value | Markets | Fills | Stated edge | ¢/contract | t | 1st half ¢ (t) | 2nd half ¢ (t) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| flow 1, fee 0c | no model filter | 1,076 | 811 | +0.00 | +0.15 | 0.08 | +1.41 (0.55) | -1.49 (-0.53) |
| flow 1, fee 0c | ESPN line, normal | 657 | 391 | +1.78 | +3.25 | 1.25 | +2.52 (0.73) | +4.25 (1.07) |
| flow 1, fee 0c | ESPN line, empirical | 633 | 377 | +1.78 | +3.62 | 1.36 | +3.39 (0.95) | +3.93 (0.99) |
| flow 1, fee 1c | no model filter | 1,076 | 811 | +0.00 | -0.85 | -0.45 | +0.41 (0.16) | -2.49 (-0.88) |
| flow 1, fee 1c | ESPN line, normal | 657 | 391 | +1.78 | +2.25 | 0.86 | +1.52 (0.44) | +3.25 (0.82) |
| flow 1, fee 1c | ESPN line, empirical | 633 | 377 | +1.78 | +2.62 | 0.99 | +2.39 (0.67) | +2.93 (0.74) |
| flow 0.25, fee 0c | no model filter | 1,076 | 794 | +0.00 | +0.37 | 0.19 | +1.76 (0.69) | -1.44 (-0.50) |
| flow 0.25, fee 0c | ESPN line, normal | 657 | 378 | +1.78 | +3.34 | 1.26 | +2.49 (0.71) | +4.49 (1.11) |
| flow 0.25, fee 0c | ESPN line, empirical | 633 | 364 | +1.77 | +3.73 | 1.38 | +3.39 (0.93) | +4.18 (1.04) |
| flow 0.25, fee 1c | no model filter | 1,076 | 794 | +0.00 | -0.63 | -0.33 | +0.76 (0.30) | -2.44 (-0.85) |
| flow 0.25, fee 1c | ESPN line, normal | 657 | 378 | +1.78 | +2.34 | 0.88 | +1.49 (0.42) | +3.49 (0.86) |
| flow 0.25, fee 1c | ESPN line, empirical | 633 | 364 | +1.77 | +2.73 | 1.01 | +2.39 (0.65) | +3.18 (0.79) |

## Overlap with player-points props

Across 17,268 points props in 1,030 games, every 10 points the game total beats ESPN's line raises the props' over rate by +3.3 points (correlation 0.14). NO on a total and NO on points overs in the same game lose together.
