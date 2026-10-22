# Ladder prices from the sportsbooks (test C; exploratory, in-sample, simulated)

Plan: RESEARCH_LOG.md, 2026-10-22, test C. Variants: negative binomial and normal (2). 2025-26 season, 151 games with sportsbook history. Replay fills come from public trade prints as if first in line (flow share 1.0) or as the expected fill at flow share 0.25; nothing here is live.

Rungs in those games: 7,777; posted before the game's book snapshot (excluded): 233; no book line at all for the player and stat (excluded): 326. Priced: 7,218 in 150 games; exact line with 2+ books 2,540, with 1 book 1,987, not quoted 2,691.

## Fit check

Ladders (player-stat-game) by number of book lines: {'1': 2066, '2': 1254, '3+': 4280}.
Single-line ladders use a per-stat shape from 3+ line ladders before 2026-02-09:

| Stat | NB size | ladders | Normal sd / mean | ladders |
|---|---:|---:|---:|---:|
| assists | 23.05 | 322 | 0.516 | 322 |
| points | 6.40 | 891 | 0.487 | 891 |
| rebounds | 16.40 | 613 | 0.510 | 613 |
| threes | 11.76 | 359 | 0.857 | 359 |

Fitted minus book probability at the book's own lines (absolute):

| Lines | NB median | NB 90th pct | Normal median | Normal 90th pct | Lines (n) |
|---|---:|---:|---:|---:|---:|
| all lines | 0.0038 | 0.0136 | 0.0050 | 0.0168 | 32,551 |
| ladders with 3+ lines | 0.0047 | 0.0143 | 0.0061 | 0.0180 | 27,977 |
| ladders with 2 lines | 0.0000 | 0.0005 | 0.0000 | 0.0000 | 2,508 |
| single-line ladders | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 2,066 |
| lines with 2+ books | 0.0027 | 0.0098 | 0.0034 | 0.0103 | 15,349 |

Ladders ending on a parameter bound: NB 176, normal 4.

## Calibration on Kalshi rungs (outcomes, in-sample)

**All rungs with a ladder**: 7,218 rungs, 150 games, over rate 0.448.

| Source | Log loss | Brier |
|---|---:|---:|
| Ladder, negative binomial | 0.5426 | 0.1829 |
| Ladder, normal | 0.5441 | 0.1830 |
| Stat model | 0.5535 | 0.1865 |
| Kalshi mid at posting | 0.5528 | 0.1873 |
| Live rule (2-book exact line, else model) | 0.5510 | 0.1854 |

| Paired log loss | A minus B | clustered t |
|---|---:|---:|
| Ladder, negative binomial − Stat model | -0.0108 | -2.69 |
| Ladder, negative binomial − Kalshi mid at posting | -0.0102 | -3.6 |
| Ladder, negative binomial − Live rule (2-book exact line, else model) | -0.0084 | -3.34 |
| Ladder, normal − Stat model | -0.0094 | -2.36 |
| Ladder, normal − Kalshi mid at posting | -0.0088 | -3.3 |
| Ladder, normal − Live rule (2-book exact line, else model) | -0.0069 | -2.66 |
| Ladder, negative binomial − Ladder, normal | -0.0014 | -1.1 |

**No exact line with 2+ books**: 4,678 rungs, 146 games, over rate 0.434.

| Source | Log loss | Brier |
|---|---:|---:|
| Ladder, negative binomial | 0.4684 | 0.1502 |
| Ladder, normal | 0.4705 | 0.1502 |
| Stat model | 0.4814 | 0.1542 |
| Kalshi mid at posting | 0.4798 | 0.1550 |
| Live rule (2-book exact line, else model) | 0.4814 | 0.1542 |

| Paired log loss | A minus B | clustered t |
|---|---:|---:|
| Ladder, negative binomial − Stat model | -0.0130 | -3.34 |
| Ladder, negative binomial − Kalshi mid at posting | -0.0114 | -3.18 |
| Ladder, negative binomial − Live rule (2-book exact line, else model) | -0.0130 | -3.34 |
| Ladder, normal − Stat model | -0.0109 | -2.71 |
| Ladder, normal − Kalshi mid at posting | -0.0093 | -2.84 |
| Ladder, normal − Live rule (2-book exact line, else model) | -0.0109 | -2.71 |
| Ladder, negative binomial − Ladder, normal | -0.0021 | -1.02 |

**Exact line with 2+ books**: 2,540 rungs, 147 games, over rate 0.475.

| Source | Log loss | Brier |
|---|---:|---:|
| Ladder, negative binomial | 0.6793 | 0.2431 |
| Ladder, normal | 0.6795 | 0.2433 |
| Stat model | 0.6862 | 0.2460 |
| Kalshi mid at posting | 0.6873 | 0.2467 |
| Live rule (2-book exact line, else model) | 0.6791 | 0.2431 |

| Paired log loss | A minus B | clustered t |
|---|---:|---:|
| Ladder, negative binomial − Stat model | -0.0069 | -1.2 |
| Ladder, negative binomial − Kalshi mid at posting | -0.0080 | -2.55 |
| Ladder, negative binomial − Live rule (2-book exact line, else model) | +0.0002 | 0.76 |
| Ladder, normal − Stat model | -0.0067 | -1.14 |
| Ladder, normal − Kalshi mid at posting | -0.0077 | -2.44 |
| Ladder, normal − Live rule (2-book exact line, else model) | +0.0004 | 1.97 |
| Ladder, negative binomial − Ladder, normal | -0.0003 | -1.16 |

## Replay (simulated): one-contract NO, 0-15¢ edge, NO 5-95¢, no caps, no fee

Stated edge: the source's fair value minus our price, averaged over fills. t: game-clustered.

**All rungs with a ladder, flow share 1**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 4,006 | 2,434.0 | +1.79 | +3.93 | 2.84 | +2.39 | 2.83 |
| Ladder, normal | 4,938 | 3,000.0 | +2.27 | +3.05 | 2.49 | +1.85 | 2.48 |
| Stat model | 4,296 | 2,630.0 | +5.70 | +2.56 | 1.8 | +1.57 | 1.79 |
| Live rule (2-book exact line, else model) | 4,508 | 2,779.0 | +3.67 | +3.16 | 2.31 | +1.95 | 2.31 |

**No exact line with 2+ books, flow share 1**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 2,225 | 1,183.0 | +1.94 | +4.59 | 3.13 | +2.44 | 3.09 |
| Ladder, normal | 3,322 | 1,887.0 | +2.69 | +3.16 | 2.62 | +1.79 | 2.6 |
| Stat model | 2,765 | 1,568.0 | +5.28 | +2.26 | 1.7 | +1.28 | 1.7 |
| Live rule (2-book exact line, else model) | 2,765 | 1,568.0 | +5.28 | +2.26 | 1.7 | +1.28 | 1.7 |

**Exact line with 2+ books, flow share 1**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 1,781 | 1,251.0 | +1.64 | +3.31 | 1.78 | +2.33 | 1.78 |
| Ladder, normal | 1,616 | 1,113.0 | +1.56 | +2.86 | 1.51 | +1.97 | 1.51 |
| Stat model | 1,531 | 1,062.0 | +6.33 | +2.99 | 1.51 | +2.08 | 1.51 |
| Live rule (2-book exact line, else model) | 1,743 | 1,211.0 | +1.59 | +4.31 | 2.31 | +3.00 | 2.32 |

**All rungs with a ladder, flow share 0.25**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 4,006 | 2,301.5 | +1.76 | +4.00 | 2.79 | +2.30 | 2.78 |
| Ladder, normal | 4,938 | 2,840.0 | +2.22 | +3.04 | 2.42 | +1.75 | 2.41 |
| Stat model | 4,296 | 2,502.9 | +5.72 | +2.43 | 1.67 | +1.41 | 1.67 |
| Live rule (2-book exact line, else model) | 4,508 | 2,647.4 | +3.65 | +3.07 | 2.18 | +1.80 | 2.18 |

**No exact line with 2+ books, flow share 0.25**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 2,225 | 1,094.1 | +1.91 | +4.95 | 3.27 | +2.43 | 3.21 |
| Ladder, normal | 3,322 | 1,767.8 | +2.63 | +3.31 | 2.67 | +1.76 | 2.65 |
| Stat model | 2,765 | 1,476.2 | +5.29 | +2.22 | 1.61 | +1.18 | 1.61 |
| Live rule (2-book exact line, else model) | 2,765 | 1,476.2 | +5.29 | +2.22 | 1.61 | +1.18 | 1.61 |

**Exact line with 2+ books, flow share 0.25**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 1,781 | 1,207.4 | +1.63 | +3.14 | 1.65 | +2.13 | 1.66 |
| Ladder, normal | 1,616 | 1,072.2 | +1.54 | +2.60 | 1.35 | +1.73 | 1.35 |
| Stat model | 1,531 | 1,026.6 | +6.34 | +2.73 | 1.37 | +1.83 | 1.37 |
| Live rule (2-book exact line, else model) | 1,743 | 1,171.1 | +1.57 | +4.15 | 2.19 | +2.79 | 2.19 |

### By half, rungs with no 2-book exact line

**before 2026-02-09, flow share 1**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 610 | 313.0 | +2.36 | +6.51 | 1.92 | +3.34 | 1.88 |
| Ladder, normal | 836 | 433.0 | +2.97 | +4.16 | 1.33 | +2.16 | 1.32 |
| Stat model | 703 | 359.0 | +5.64 | +1.49 | 0.41 | +0.76 | 0.4 |
| Live rule (2-book exact line, else model) | 703 | 359.0 | +5.64 | +1.49 | 0.41 | +0.76 | 0.4 |

**from 2026-02-09, flow share 1**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 1,615 | 870.0 | +1.78 | +3.90 | 2.48 | +2.10 | 2.45 |
| Ladder, normal | 2,486 | 1,454.0 | +2.60 | +2.86 | 2.27 | +1.67 | 2.26 |
| Stat model | 2,062 | 1,209.0 | +5.17 | +2.49 | 1.84 | +1.46 | 1.84 |
| Live rule (2-book exact line, else model) | 2,062 | 1,209.0 | +5.17 | +2.49 | 1.84 | +1.46 | 1.84 |

**before 2026-02-09, flow share 0.25**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 610 | 286.1 | +2.33 | +6.62 | 1.88 | +3.11 | 1.83 |
| Ladder, normal | 836 | 400.5 | +2.89 | +4.26 | 1.33 | +2.04 | 1.31 |
| Stat model | 703 | 337.5 | +5.66 | +1.48 | 0.39 | +0.71 | 0.39 |
| Live rule (2-book exact line, else model) | 703 | 337.5 | +5.66 | +1.48 | 0.39 | +0.71 | 0.39 |

**from 2026-02-09, flow share 0.25**

| Fair value | Eligible | Fills | Stated edge ¢ | ¢ per fill | t | $ per 100 eligible | t |
|---|---:|---:|---:|---:|---:|---:|---:|
| Ladder, negative binomial | 1,615 | 808.0 | +1.76 | +4.35 | 2.68 | +2.18 | 2.64 |
| Ladder, normal | 2,486 | 1,367.3 | +2.55 | +3.03 | 2.33 | +1.66 | 2.31 |
| Stat model | 2,062 | 1,138.8 | +5.18 | +2.44 | 1.74 | +1.35 | 1.75 |
| Live rule (2-book exact line, else model) | 2,062 | 1,138.8 | +5.18 | +2.44 | 1.74 | +1.35 | 1.75 |

### Paired: ladder minus live rule, $ per 100 rungs (same rungs)

| Flow share | Rungs | Half | Ladder | Rungs (n) | $ per 100 rungs | t |
|---|---|---|---|---:|---:|---:|
| 1 | All rungs with a ladder | all | Ladder, negative binomial | 7,218 | +0.11 | 0.48 |
| 1 | All rungs with a ladder | all | Ladder, normal | 7,218 | +0.05 | 0.24 |
| 1 | All rungs with a ladder | h1 | Ladder, negative binomial | 2,039 | +0.49 | 1.05 |
| 1 | All rungs with a ladder | h1 | Ladder, normal | 2,039 | +0.40 | 0.95 |
| 1 | All rungs with a ladder | h2 | Ladder, negative binomial | 5,179 | -0.04 | -0.15 |
| 1 | All rungs with a ladder | h2 | Ladder, normal | 5,179 | -0.09 | -0.36 |
| 1 | No exact line with 2+ books | all | Ladder, negative binomial | 4,678 | +0.40 | 1.29 |
| 1 | No exact line with 2+ books | all | Ladder, normal | 4,678 | +0.51 | 1.78 |
| 1 | No exact line with 2+ books | h1 | Ladder, negative binomial | 1,212 | +1.24 | 1.78 |
| 1 | No exact line with 2+ books | h1 | Ladder, normal | 1,212 | +1.05 | 1.6 |
| 1 | No exact line with 2+ books | h2 | Ladder, negative binomial | 3,466 | +0.11 | 0.32 |
| 1 | No exact line with 2+ books | h2 | Ladder, normal | 3,466 | +0.33 | 1.04 |
| 1 | Exact line with 2+ books | all | Ladder, negative binomial | 2,540 | -0.42 | -1.87 |
| 1 | Exact line with 2+ books | all | Ladder, normal | 2,540 | -0.80 | -3.25 |
| 1 | Exact line with 2+ books | h1 | Ladder, negative binomial | 827 | -0.60 | -1.62 |
| 1 | Exact line with 2+ books | h1 | Ladder, normal | 827 | -0.55 | -1.44 |
| 1 | Exact line with 2+ books | h2 | Ladder, negative binomial | 1,713 | -0.34 | -1.19 |
| 1 | Exact line with 2+ books | h2 | Ladder, normal | 1,713 | -0.93 | -2.92 |
| 0.25 | All rungs with a ladder | all | Ladder, negative binomial | 7,218 | +0.15 | 0.66 |
| 0.25 | All rungs with a ladder | all | Ladder, normal | 7,218 | +0.07 | 0.34 |
| 0.25 | All rungs with a ladder | h1 | Ladder, negative binomial | 2,039 | +0.45 | 0.98 |
| 0.25 | All rungs with a ladder | h1 | Ladder, normal | 2,039 | +0.36 | 0.85 |
| 0.25 | All rungs with a ladder | h2 | Ladder, negative binomial | 5,179 | +0.03 | 0.11 |
| 0.25 | All rungs with a ladder | h2 | Ladder, normal | 5,179 | -0.04 | -0.18 |
| 0.25 | No exact line with 2+ books | all | Ladder, negative binomial | 4,678 | +0.46 | 1.48 |
| 0.25 | No exact line with 2+ books | all | Ladder, normal | 4,678 | +0.55 | 1.92 |
| 0.25 | No exact line with 2+ books | h1 | Ladder, negative binomial | 1,212 | +1.15 | 1.68 |
| 0.25 | No exact line with 2+ books | h1 | Ladder, normal | 1,212 | +1.00 | 1.53 |
| 0.25 | No exact line with 2+ books | h2 | Ladder, negative binomial | 3,466 | +0.21 | 0.63 |
| 0.25 | No exact line with 2+ books | h2 | Ladder, normal | 3,466 | +0.39 | 1.26 |
| 0.25 | Exact line with 2+ books | all | Ladder, negative binomial | 2,540 | -0.42 | -1.96 |
| 0.25 | Exact line with 2+ books | all | Ladder, normal | 2,540 | -0.81 | -3.45 |
| 0.25 | Exact line with 2+ books | h1 | Ladder, negative binomial | 827 | -0.57 | -1.54 |
| 0.25 | Exact line with 2+ books | h1 | Ladder, normal | 827 | -0.58 | -1.52 |
| 0.25 | Exact line with 2+ books | h2 | Ladder, negative binomial | 1,713 | -0.34 | -1.32 |
| 0.25 | Exact line with 2+ books | h2 | Ladder, normal | 1,713 | -0.93 | -3.11 |
