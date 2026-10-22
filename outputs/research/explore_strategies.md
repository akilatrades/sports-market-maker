# A different strategy across all scanned Kalshi markets (exploratory, simulated)

202,805 markets, 1,763 series, 99,555 events; halves split at 2026-05-10. Taker at the quoted ask, one contract, held to settlement.

## Calibration: realised YES rate minus the mid at the first quote

| Mid band | Markets | Mid | YES rate | Gap (¢) | t |
|---|---:|---:|---:|---:|---:|
| (-0.001, 0.05] | 12,976 | 0.031 | 0.026 | -0.46 | -3.29 |
| (0.05, 0.1] | 13,808 | 0.076 | 0.073 | -0.32 | -1.44 |
| (0.1, 0.2] | 24,996 | 0.153 | 0.152 | -0.07 | -0.31 |
| (0.2, 0.35] | 45,428 | 0.275 | 0.275 | -0.01 | -0.05 |
| (0.35, 0.5] | 44,511 | 0.433 | 0.422 | -1.08 | -4.56 |
| (0.5, 0.65] | 30,509 | 0.569 | 0.564 | -0.49 | -1.70 |
| (0.65, 0.8] | 18,337 | 0.722 | 0.726 | +0.34 | 1.01 |
| (0.8, 0.9] | 7,376 | 0.847 | 0.853 | +0.55 | 1.31 |
| (0.9, 0.95] | 2,829 | 0.927 | 0.938 | +1.12 | 2.41 |
| (0.95, 1.0] | 2,035 | 0.969 | 0.976 | +0.68 | 1.87 |

Favourite side (mid ≥ 80¢ or ≤ 20¢), realised minus price, by category:

| Category | Markets | Favourite markets | Gap (¢) | t |
|---|---:|---:|---:|---:|
| crypto | 191 | 148 | -0.57 | -0.25 |
| economics | 4,467 | 3,106 | +2.46 | 5.23 |
| entertainment | 490 | 332 | +2.82 | 2.13 |
| mentions | 1,806 | 805 | +1.25 | 1.25 |
| other | 22,837 | 10,202 | +1.06 | 3.81 |
| politics | 970 | 376 | +2.12 | 1.74 |
| sports | 172,044 | 49,418 | +0.01 | 0.08 |

## Rules (taker fee unrounded = a large order; one-contract fee in brackets)

| Rule | Trades | Win rate | Avg price | ¢/contract (t) | 1-contract fee ¢ | No fee ¢ | Earlier ¢ (t) | Later ¢ (t) | Top series share | Promising |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| S1 favourite at 80c+ | 88,830 | 0.829 | 0.908 | -8.53 (-56.05) | -9.11 | -7.97 | -8.45 (-38.62) | -8.59 (-40.74) | 4% (KXINTLFRIENDLYGAME) | no |
| S1 favourite at 90c+ | 53,167 | 0.855 | 0.956 | -10.33 (-53.52) | -11.03 | -10.03 | -11.11 (-38.62) | -9.75 (-37.54) | 3% (KXBOXING) | no |
| S1 favourite at 95c+ | 35,083 | 0.856 | 0.974 | -11.98 (-51.44) | -12.80 | -11.80 | -13.29 (-37.59) | -10.98 (-35.38) | 2% (KXNASCARRACE) | no |
| S2 momentum | 20,779 | 0.584 | 0.707 | -13.32 (-37.71) | -13.84 | -12.23 | -14.59 (-26.78) | -12.36 (-26.61) | 2% (KXHNLGAME) | no |
| S2 reversal | 20,779 | 0.416 | 0.491 | -8.72 (-27.06) | -9.20 | -7.51 | -8.63 (-17.13) | -8.79 (-21.00) | 3% (KXNBASUMMERSPREAD) | no |
| S1b favourite mid 80c+, spread <= 3c | 45,545 | 0.904 | 0.909 | -1.04 (-7.25) | -1.58 | -0.49 | -0.75 (-3.23) | -1.24 (-6.76) | 3% (KXINTLFRIENDLYGAME) | no |
| S1b favourite mid 90c+, spread <= 3c | 24,113 | 0.954 | 0.956 | -0.56 (-4.00) | -1.27 | -0.27 | -0.13 (-0.58) | -0.79 (-4.45) | 3% (KXBOXING) | no |
| S2b momentum, spread <= 3c | 6,027 | 0.677 | 0.675 | -0.99 (-1.73) | -1.49 | +0.15 | -1.76 (-1.66) | -0.61 (-0.90) | 3% (KXLOLGAME) | no |
| S2b reversal, spread <= 3c | 6,027 | 0.323 | 0.341 | -2.98 (-5.18) | -3.46 | -1.81 | -2.49 (-2.34) | -3.23 (-4.75) | 2% (KXWNBA1HTOTAL) | no |

## Extra: resting orders on the favourite side (maker, 80-98¢, scan's maker fee)

| Category | Fills | Avg price | ¢/contract (t) | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|
| all | 36,623 | 0.887 | -0.05 (-0.27) | +0.56 (2.16) | -0.50 (-2.20) |
| crypto | 54 | 0.919 | -1.26 (-0.34) | -4.86 (-0.89) | +5.96 (6.89) |
| economics | 1,241 | 0.903 | +1.51 (1.80) | +2.24 (2.05) | +0.72 (0.56) |
| entertainment | 101 | 0.925 | +1.42 (0.53) | -1.18 (-0.33) | +8.19 (7.70) |
| mentions | 615 | 0.889 | +0.41 (0.32) | +0.09 (0.07) | +7.22 (5.25) |
| other | 5,262 | 0.904 | +0.96 (2.46) | +2.20 (2.63) | +0.71 (1.61) |
| politics | 205 | 0.887 | -0.54 (-0.24) | +1.41 (0.44) | -1.98 (-0.63) |
| sports | 29,145 | 0.883 | -0.30 (-1.53) | +0.41 (1.42) | -0.91 (-3.34) |

## By category (large-order fee; earlier half → later half)

**S1 favourite at 80c+** (best on the earlier half: politics)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 120 | -5.41 (-1.83) | 42 | -0.66 (-0.20) |
| economics | 1,878 | -1.82 (-2.37) | 1,580 | -0.50 (-0.75) |
| entertainment | 323 | -8.79 (-3.47) | 99 | +1.50 (1.05) |
| mentions | 943 | -5.73 (-4.16) | 68 | +1.80 (0.50) |
| other | 3,727 | -8.74 (-12.26) | 9,407 | -6.41 (-16.56) |
| politics | 179 | +1.10 (0.56) | 241 | -0.46 (-0.27) |
| sports | 32,719 | -8.94 (-36.56) | 37,504 | -9.59 (-37.85) |

**S1 favourite at 90c+** (best on the earlier half: economics)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 102 | -5.93 (-1.90) | 38 | +0.32 (0.12) |
| economics | 1,428 | -2.41 (-3.04) | 1,246 | -0.96 (-1.49) |
| entertainment | 279 | -7.89 (-3.31) | 94 | +0.88 (0.60) |
| mentions | 554 | -5.56 (-3.46) | 54 | +1.83 (1.05) |
| other | 2,893 | -8.70 (-11.26) | 7,024 | -6.09 (-15.29) |
| politics | 95 | +0.22 (0.12) | 184 | +0.15 (0.11) |
| sports | 17,028 | -12.58 (-37.62) | 22,148 | -11.58 (-35.21) |

**S1 favourite at 95c+** (best on the earlier half: economics)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 83 | -6.38 (-1.86) | 28 | -1.93 (-0.55) |
| economics | 1,033 | -2.93 (-3.43) | 970 | -1.13 (-1.69) |
| entertainment | 222 | -9.59 (-3.50) | 79 | +0.92 (0.73) |
| mentions | 397 | -5.41 (-1.91) | 43 | +2.88 (14.06) |
| other | 2,310 | -9.38 (-10.99) | 4,986 | -6.61 (-14.68) |
| politics | 56 | +2.11 (10.65) | 121 | -1.08 (-0.68) |
| sports | 10,993 | -15.57 (-37.82) | 13,762 | -13.48 (-33.27) |

**S2 momentum** (best on the earlier half: economics)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 42 | -9.40 (-1.50) | 17 | -11.77 (-1.39) |
| economics | 472 | -7.98 (-3.69) | 658 | -4.75 (-3.54) |
| entertainment | 34 | -42.72 (-4.17) | 8 | -20.47 (-2.05) |
| mentions | 662 | -15.15 (-6.98) | 9 | -0.79 (-0.12) |
| other | 1,365 | -15.81 (-11.31) | 2,462 | -11.91 (-10.74) |
| politics | 15 | -11.72 (-0.85) | 22 | -29.27 (-2.94) |
| sports | 6,335 | -14.65 (-22.79) | 8,678 | -13.03 (-24.16) |

**S2 reversal** (best on the earlier half: mentions)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 42 | -3.61 (-0.64) | 17 | +0.54 (0.06) |
| economics | 472 | -8.38 (-4.92) | 658 | -7.15 (-5.94) |
| entertainment | 34 | -8.06 (-1.65) | 8 | +0.38 (0.04) |
| mentions | 662 | -7.24 (-3.75) | 9 | -11.67 (-2.36) |
| other | 1,365 | -12.77 (-10.16) | 2,462 | -9.88 (-11.07) |
| politics | 15 | -4.88 (-0.40) | 22 | +9.32 (0.78) |
| sports | 6,335 | -7.95 (-13.09) | 8,678 | -8.67 (-17.25) |

**S1b favourite mid 80c+, spread <= 3c** (best on the earlier half: politics)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 50 | -0.10 (-0.04) | 29 | +2.81 (5.74) |
| economics | 1,096 | +0.51 (0.65) | 1,025 | +0.75 (1.11) |
| entertainment | 128 | -3.45 (-1.35) | 49 | +2.49 (8.75) |
| mentions | 522 | -1.37 (-1.08) | 36 | +5.36 (3.21) |
| other | 1,232 | +0.09 (0.14) | 5,102 | -1.14 (-3.21) |
| politics | 129 | +1.06 (0.50) | 197 | +0.19 (0.12) |
| sports | 15,029 | -0.89 (-3.34) | 20,921 | -1.40 (-6.35) |

**S1b favourite mid 90c+, spread <= 3c** (best on the earlier half: other)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 42 | +1.94 (7.25) | 28 | +2.54 (5.55) |
| economics | 797 | +0.20 (0.27) | 819 | +0.51 (0.84) |
| entertainment | 107 | -1.92 (-0.94) | 49 | +2.49 (8.75) |
| mentions | 316 | -0.25 (-0.27) | 30 | +3.36 (8.21) |
| other | 967 | +0.90 (1.97) | 3,730 | -0.73 (-2.29) |
| politics | 65 | +1.15 (0.62) | 144 | +0.24 (0.17) |
| sports | 6,047 | -0.33 (-1.16) | 10,972 | -0.95 (-4.24) |

**S2b momentum, spread <= 3c** (best on the earlier half: mentions)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 7 | +5.65 (1.86) | 7 | +0.61 (0.10) |
| economics | 113 | -0.27 (-0.09) | 372 | +2.36 (1.65) |
| entertainment | 5 | +12.26 (2.89) | 3 | -7.93 (-1.15) |
| mentions | 126 | +3.72 (0.93) | 5 | +7.79 (1.52) |
| other | 155 | +1.91 (0.68) | 771 | +0.05 (0.03) |
| politics | 8 | +2.65 (0.14) | 9 | -30.37 (-1.62) |
| sports | 1,592 | -2.76 (-2.21) | 2,854 | -1.10 (-1.30) |

**S2b reversal, spread <= 3c** (best on the earlier half: sports)

| Category | Earlier trades | Earlier ¢ (t) | Later trades | Later ¢ (t) |
|---|---:|---:|---:|---:|
| crypto | 7 | -8.32 (-2.57) | 7 | -3.91 (-0.64) |
| economics | 113 | -3.33 (-1.05) | 372 | -5.36 (-3.76) |
| entertainment | 5 | -15.78 (-3.27) | 3 | +5.11 (0.87) |
| mentions | 126 | -7.69 (-1.93) | 5 | -11.25 (-1.75) |
| other | 155 | -5.36 (-1.91) | 771 | -3.92 (-2.58) |
| politics | 8 | -7.36 (-0.39) | 9 | +26.79 (1.43) |
| sports | 1,592 | -1.64 (-1.32) | 2,854 | -2.86 (-3.39) |
