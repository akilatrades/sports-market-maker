# Where is the NO edge thicker? D. Other markets

*Exploratory, simulated, in-sample.* Replays of public Kalshi trade prints
from the cross-market scan (each series' sample covers part of the 400
days before 2026-10-16). One contract per hourly order, filled as if first
in line (flow share 1.0) unless marked 0.25. Scan maker fee (a quarter of
0.07 x P x (1 - P), not rounded) unless marked. t is clustered by event
(the game for sports). Nothing here is live P&L or a forecast.

## 1. Time holdout: top 10 on the earlier half, scored on the later half

Each series' markets split at its median expiry date. Ranked by earlier-half cents per filled contract among the 470 series with at least 30 earlier-half fills in at least 10 events.

| # | Series | Earlier fills | Earlier ¢ | Earlier t | Later fills (events) | Later ¢ | Later t | Later ¢ at 0.25 | Avg NO price | Fee type seen |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | KXJOBLESSCLAIMS | 54 | +31.0 | 2.63 | 3 (3) † | +22.6 | 1.19 | +34.1 | 0.46 | not recorded |
| 2 | KXFACUPTOTAL | 59 | +21.9 | 2.07 | 127 (16) | -4.4 | -0.50 | -4.5 | 0.48 | not recorded |
| 3 | KXIPLFOUR | 30 | +19.3 | 1.93 | 42 (17) | -1.0 | -0.09 | -0.4 | 0.46 | not recorded |
| 4 | KXNCAAMB1HSPREAD | 78 | +19.2 | 2.82 | 145 (70) | +14.8 | 2.84 | +15.0 | 0.56 | quadratic x1 |
| 5 | KXKBOSPREAD | 64 | +18.0 | 2.55 | 131 (66) | -1.4 | -0.20 | -1.8 | 0.62 | not recorded |
| 6 | KXALLSVENSKANTOTAL | 95 | +17.9 | 2.21 | 93 (16) | -7.6 | -0.92 | -7.0 | 0.48 | not recorded |
| 7 | KXIPLSIX | 37 | +17.5 | 1.59 | 52 (20) | +16.5 | 1.97 | +16.5 | 0.43 | not recorded |
| 8 | KXUEL1HTOTAL | 48 | +16.2 | 2.42 | 103 (21) | +0.2 | 0.03 | -0.6 | 0.56 | not recorded |
| 9 | KXLEAGUESCUPBTTS | 72 | +15.8 | 1.50 | 70 (31) | -13.0 | -1.57 | -13.0 | 0.38 | not recorded |
| 10 | KXNFLTEAMTOTAL | 32 | +15.0 | 0.78 | 72 (13) | +4.2 | 0.52 | +4.8 | 0.36 | not recorded |

† fewer than 30 later-half fills. Fee type: as recorded on 2026-10-18 for the few series checked then.

- Mean of the 10: earlier +19.2¢, later +3.1¢; later half positive in 5 of 10, t ≥ 2 in 1.
- The 10 pooled, later half: 838 fills, +1.20¢, t 0.44 (by expiry day 0.47).
- Baseline, all 470 ranked series pooled, later half: 116,831 fills, +0.42¢, t 2.20 (mean of series +0.45¢).
- Extra variant, ranked by earlier-half t instead: later mean +4.9¢, positive in 8 of 10, pooled 1,523 fills +3.64¢ t 2.51 (by day 2.66); series: KXUECLSCORE (+2.7¢), KXWNBAOT (+1.3¢), KXNBAOVERTIME (-2.6¢), KXNCAABMENTION (+7.1¢), KXVTBGAME (+0.0¢), KXAHLGAME (+1.2¢), KXNCAAMB1HSPREAD (+14.8¢), KXWNBA1QWINNER (+2.6¢), KXGOLDW (-0.5¢), KXJOBLESSCLAIMS (+22.6¢).

## 2. Multiple testing on the full samples

654 of 1763 series have at least 30 fills in 10+ events. t ≥ 2: **45** (expected with no edge anywhere: 15 normal, 17 with events − 1 degrees of freedom); t ≤ −2: 20. Benjamini-Hochberg at 10% on one-sided p values: **6 survive**.

| Series | Fills | Events | Avg NO price | Losing fills | ¢ | t | q | Earlier ¢ | Later ¢ | Sample dates |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| KXNHLFIRSTGOAL | 62 | 25 | 0.95 | 0 | +4.7 | 7.88 | 0.000 | +7.7 | +3.4 | 2025-11-22 to 2026-06-12 |
| KXNCAAMB1HSPREAD | 223 | 116 | 0.56 | 61 | +16.4 | 3.97 | 0.021 | +19.2 | +14.8 | 2026-02-18 to 2026-04-07 |
| KXNWSLSPREAD | 145 | 39 | 0.77 | 12 | +14.0 | 4.04 | 0.027 | +13.0 | +15.5 | 2026-07-18 to 2026-08-16 |
| KXNCAABMENTION | 679 | 100 | 0.44 | 310 | +9.5 | 3.65 | 0.034 | +12.4 | +7.1 | 2026-01-31 to 2026-03-23 |
| KXNASCARRACE | 940 | 73 | 0.90 | 55 | +4.0 | 3.62 | 0.035 | +3.9 | +4.1 | 2025-09-13 to 2026-08-16 |
| KXCLUBFBTTS | 567 | 257 | 0.40 | 273 | +11.5 | 3.36 | 0.048 | +13.5 | +10.1 | 2026-07-22 to 2026-08-16 |

A series with no losing fills has a t that measures only how alike its
small wins are; one loss at a 95¢ NO price erases about 19 of them.

## 3. The series singled out earlier (descriptive)

Chosen on their full samples, so both halves here are in-sample.

| Series | Fills | Events | ¢ | t | BH q | Earlier ¢ (rank) | Later ¢ | Later t | Later fills |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KXCLUBFBTTS | 567 | 257 | +11.5 | 3.36 | 0.05 | +13.5 (#13) | +10.1 | 2.28 | 337 |
| KXWNBA1HTOTAL | 675 | 247 | +8.8 | 2.55 | 0.25 | +5.3 (#81) | +13.3 | 2.32 | 296 |
| KXNBA3D | 509 | 196 | +4.5 | 2.25 | 0.30 | +4.6 (#98) | +4.4 | 1.81 | 241 |
| KXNCAAMB1HSPREAD | 223 | 116 | +16.4 | 3.97 | 0.02 | +19.2 (#4) | +14.8 | 2.84 | 145 |
| KXUCLCORNERS | 141 | 11 | +29.4 | 3.07 | 0.25 | +45.3 | +22.4 | 1.71 | 98 |
| KXUFCMOF | 218 | 94 | +8.6 | 2.29 | 0.30 | +5.8 (#69) | +10.2 | 2.59 | 141 |
| KXNBAFTM | 127 | 7 | +12.4 | 2.07 | n/a | +18.7 | +9.6 | 1.02 | 88 |
| KXNCAAMENTION | 813 | 27 | +6.5 | 2.29 | 0.31 | +2.7 (#144) | +10.0 | 2.90 | 422 |
| KXWNBA1QSPREAD | 109 | 56 | +16.4 | 2.66 | 0.25 | +10.5 (#31) | +21.2 | 2.62 | 60 |
| KXNASCARTOP10 | 108 | 11 | +14.1 | 3.53 | 0.20 | +21.7 | +8.7 | 2.59 | 63 |
| KXITFMATCH | 1,168 | 554 | +4.6 | 2.51 | 0.25 | +1.4 (#182) | +6.4 | 2.73 | 746 |
| KXNASCARRACE | 940 | 73 | +4.0 | 3.62 | 0.04 | +3.9 (#106) | +4.1 | 2.61 | 486 |
| KXNFLANYTD | 2,255 | 262 | +3.0 | 2.25 | 0.30 | +1.7 (#176) | +4.1 | 2.25 | 1,215 |
| KXLIGAMXSPREAD | 938 | 143 | +4.6 | 2.21 | 0.31 | +5.6 (#77) | +3.8 | 1.42 | 484 |
| KXLALIGASPREAD | 835 | 223 | +4.3 | 2.29 | 0.30 | +3.1 (#132) | +5.1 | 2.34 | 511 |

## 4. NBA combo markets, resting NO (scan rows)

Every hourly look in the scan's window (about 1 to 4.5 hours before tip),
each order resting one hour. Halves by game date; cells are ¢ (t, fills).

| Series | Flow | Orders | Fill rate | Fills | ¢/contract | t | ¢ per 100 orders | Before 2026-02-09 | From 2026-02-09 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KXNBA2D | 1.0 | 1,110 | 57% | 636 | +2.67 | 1.02 | +153 | -4.70 (-0.86, 161) | +5.17 (1.74, 475) |
| KXNBA2D | 0.25 | 1,110 | 56% | 622 | +2.72 | 1.05 | +152 | -4.13 (-0.76, 156) | +5.02 (1.70, 466) |
| KXNBA3D | 1.0 | 927 | 55% | 509 | +4.47 | 2.25 | +245 | +7.47 (2.24, 145) | +3.27 (1.35, 364) |
| KXNBA3D | 0.25 | 927 | 54% | 501 | +4.25 | 2.13 | +230 | +6.80 (2.06, 142) | +3.25 (1.32, 359) |

- KXNBA2D: 334 markets (of 4879 listed in data/kalshi_history) in 281 games (2025-12-04 to 2026-06-05); 6% of fills at NO 96¢+. Fees: no maker fee +2.94¢, scan fee +2.67¢, 1¢ per contract +1.94¢. Extra variants: NO 5-95¢ +3.17¢ (t 1.17, 599 fills); first look per market +0.70¢ (t 0.20, 138 fills).
- KXNBA3D: 283 markets (of 1171 listed in data/kalshi_history) in 251 games (2025-12-04 to 2026-06-13); 37% of fills at NO 96¢+. Fees: no maker fee +4.62¢, scan fee +4.47¢, 1¢ per contract +3.62¢. Extra variants: NO 5-95¢ +5.35¢ (t 1.71, 323 fills); first look per market +4.47¢ (t 1.94, 124 fills).

## Variant count

Planned: 12 (2 combo series, 10 holdout series). Extra: 12 (8 new series from ranking by t; 4 combo variants (NO 5-95¢, first look per market)). Total: 24. Fee and flow share versions are sensitivities of the same orders, not new selections.

## Data gaps

- Unreadable scan files (skipped): orders_KXCHESSMATCH.csv.gz, orders_KXCHNSLBTTS.csv.gz.
- No trade prints for KXNBA2D/KXNBA3D in data/kalshi_history, so the combo
  replay is the scan's 400-market sample with its hourly 1-hour orders, not
  a v5-style order resting until tip; there is no model filter.
