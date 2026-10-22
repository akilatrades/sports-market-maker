# Strategy sweep across all scanned markets (exploratory, simulated)

202,805 markets. Resting orders one cent inside the spread, one contract each,
filled as if first in line, held to settlement; Kalshi's maker fee only on the
series that pay one. Profit factor = winning dollars / losing dollars.

| Family | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) | Top-10 on later half ¢ (t), fills | Promising |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 NO on every market | 257,561 | +0.85 (6.69) | 1.046 | +2,195 | +1.09 (6.42) | +0.59 (3.08) | -2.82 (-0.95), 468 | yes |
| 2 YES on every market | 136,330 | -1.41 (-8.50) | 0.925 | -1,923 | -0.92 (-3.85) | -1.85 (-8.03) | -6.32 (-2.37), 836 | no |
| 3 both sides (market making) | 393,891 | +0.07 (1.12) | 1.007 | +272 | +0.44 (4.97) | -0.31 (-3.65) | +0.10 (0.06), 619 | no |
| 4 favourite side (80c+) | 63,393 | +0.55 (3.02) | 1.060 | +350 | +0.88 (3.15) | +0.28 (1.17) | +0.92 (0.24), 180 | no |
| 5 long-shot side (20c or less) | 54,900 | -0.54 (-2.95) | 0.942 | -296 | +0.02 (0.06) | -0.93 (-4.16) | -1.67 (-0.32), 54 | no |
| 6 NO where YES is 35-50c | 58,256 | +0.76 (2.46) | 1.032 | +441 | +0.83 (1.93) | +0.67 (1.53) | -2.33 (-0.30), 82 | no |
| 7 both sides, spread 5c+ | 76,694 | +2.44 (15.86) | 1.217 | +1,873 | +3.07 (14.14) | +1.70 (7.82) | +5.31 (2.29), 299 | yes |
| 8 NO after an hour with no trading | 59,944 | +0.27 (1.31) | 1.015 | +159 | +0.80 (2.94) | -0.27 (-0.90) | +1.10 (0.45), 429 | no |
| 9 NO after an hour with trading | 141,022 | +0.86 (5.57) | 1.046 | +1,209 | +0.97 (4.77) | +0.73 (3.14) | -3.16 (-1.19), 641 | yes |

## By category (later half shows whether it held)

**1 NO on every market**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 110 | -2.15 (-0.50) | 0.823 | -2 | -3.87 (-0.70) | +1.68 (0.27) |
| economics | 3,313 | +2.46 (1.79) | 1.197 | +82 | +5.20 (2.34) | +0.38 (0.22) |
| entertainment | 347 | +3.88 (1.99) | 1.454 | +13 | +3.47 (1.51) | +5.34 (1.52) |
| mentions | 3,517 | +5.50 (4.25) | 1.369 | +194 | +5.50 (4.20) | +5.62 (0.86) |
| other | 28,376 | +1.24 (3.16) | 1.079 | +352 | +0.69 (0.94) | +1.39 (3.03) |
| politics | 136 | +5.11 (1.71) | 1.454 | +7 | +2.43 (0.64) | +10.02 (2.33) |
| sports | 221,762 | +0.70 (5.14) | 1.037 | +1,549 | +0.93 (5.31) | +0.40 (1.89) |

Top 10 series on the earlier half: KXUCLCORNERS, KXJOBLESSCLAIMS, KXNATGASD, KXATPGAMETOTAL, KXWBCF5SPREAD, KXIPLFOUR, KXWBCRFI, KXIPLSIX, KXUCLTCORNERS, KXWTI

**2 YES on every market**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 99 | -3.23 (-0.99) | 0.688 | -3 | -0.71 (-0.18) | -6.80 (-1.30) |
| economics | 2,914 | -6.04 (-5.96) | 0.590 | -176 | -6.39 (-3.56) | -5.81 (-4.85) |
| entertainment | 254 | -1.26 (-0.52) | 0.864 | -3 | -1.76 (-0.52) | -0.22 (-0.08) |
| mentions | 2,827 | -4.48 (-3.16) | 0.775 | -127 | -4.51 (-3.14) | -2.25 (-0.54) |
| other | 15,854 | -1.96 (-3.86) | 0.888 | -310 | -1.41 (-1.56) | -2.11 (-3.53) |
| politics | 125 | -0.23 (-0.08) | 0.980 | -0 | +1.73 (0.40) | -1.57 (-0.42) |
| sports | 114,257 | -1.14 (-6.35) | 0.940 | -1,303 | -0.60 (-2.38) | -1.67 (-6.56) |

Top 10 series on the earlier half: KXIPLTEAMTOTAL, KXNBA2HWINNER, KXUFCDISTANCE, KXNCAAHOCKEYGAME, KXCS2MAP, KXFIBACHAMPLEAGUEGAME, KXUELSPREAD, KXCODTOTALMAPS, KXSWISSLEAGUEGAME, KXNCAAWBSPREAD

**3 both sides (market making)**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 209 | -2.67 (-1.35) | 0.657 | -6 | -2.50 (-0.84) | -2.96 (-1.95) |
| economics | 6,227 | -1.51 (-3.19) | 0.782 | -94 | +0.05 (0.06) | -2.62 (-4.38) |
| entertainment | 601 | +1.71 (2.74) | 1.447 | +10 | +1.44 (1.91) | +2.46 (2.36) |
| mentions | 6,344 | +1.05 (2.95) | 1.180 | +67 | +1.04 (2.88) | +2.05 (0.97) |
| other | 44,230 | +0.09 (0.56) | 1.012 | +42 | -0.11 (-0.30) | +0.15 (0.77) |
| politics | 261 | +2.55 (1.42) | 1.418 | +7 | +2.17 (1.15) | +2.99 (0.94) |
| sports | 336,019 | +0.07 (1.08) | 1.007 | +246 | +0.45 (4.78) | -0.36 (-3.79) |

Top 10 series on the earlier half: KXIPLTEAMTOTAL, KXWBCF5SPREAD, KXBALGAME, KXIPLSIX, KXNATGASD, KXATPGAMETOTAL, KXIPLFOUR, KXATPTOTALSETS, KXJOBLESSCLAIMS, KXNCAAHOCKEYGAME

**4 favourite side (80c+)**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 76 | +0.11 (0.03) | 1.016 | +0 | -3.37 (-0.67) | +6.41 (7.65) |
| economics | 1,279 | +1.08 (0.99) | 1.146 | +14 | +1.41 (0.81) | +0.85 (0.61) |
| entertainment | 220 | +1.38 (0.45) | 1.246 | +3 | -1.12 (-0.28) | +8.91 (11.77) |
| mentions | 1,150 | +1.03 (0.71) | 1.114 | +12 | +0.84 (0.56) | +6.89 (4.22) |
| other | 10,429 | +1.46 (3.41) | 1.205 | +152 | +2.63 (2.83) | +1.26 (2.65) |
| politics | 71 | +2.45 (0.65) | 1.414 | +2 | +1.05 (0.24) | +4.27 (0.65) |
| sports | 50,168 | +0.33 (1.60) | 1.035 | +167 | +0.78 (2.61) | -0.12 (-0.43) |

Top 10 series on the earlier half: KXCSGOGAME, KXHNLGAME, KXABAGAME, KXNCAAFSPREAD, KXLOLMAP, KXEUROCUPGAME, KXCS2GAME, KXAFCONGAME, KXVTBGAME, KXBUNDESLIGAGAME

**5 long-shot side (20c or less)**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 73 | -2.97 (-0.93) | 0.567 | -2 | -0.63 (-0.13) | -7.48 (-8.03) |
| economics | 2,336 | -2.40 (-3.29) | 0.657 | -56 | -0.48 (-0.31) | -3.53 (-4.89) |
| entertainment | 231 | -1.43 (-0.49) | 0.791 | -3 | +1.40 (0.34) | -7.79 (-9.89) |
| mentions | 1,292 | +0.91 (0.70) | 1.098 | +12 | +1.05 (0.80) | -5.81 (-4.96) |
| other | 7,699 | -1.09 (-2.36) | 0.869 | -84 | -1.01 (-1.19) | -1.12 (-2.04) |
| politics | 104 | +1.26 (0.26) | 1.179 | +1 | -3.67 (-0.77) | +3.87 (0.56) |
| sports | 43,165 | -0.38 (-1.81) | 0.961 | -164 | +0.08 (0.23) | -0.71 (-2.79) |

Top 10 series on the earlier half: KXALEAGUEGAME, KXNCAAWBSPREAD, KXNCAAHOCKEYGAME, KXJOBLESSCLAIMS, KXNCAAMB1HWINNER, KXIPLTEAMTOTAL, KXLOLTOTALMAPS, KXWOCURLGAME, KXUNITEDCUPMATCH, KXNBAREB

**6 NO where YES is 35-50c**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 6 | +38.67 (1.84) | 5.549 | +2 | +71.50 (2.92) | +22.25 (0.61) |
| economics | 396 | +4.53 (1.30) | 1.205 | +18 | +5.88 (1.18) | +3.20 (0.66) |
| entertainment | 27 | +3.93 (0.38) | 1.227 | +1 | +3.93 (0.38) | n/a |
| mentions | 588 | +8.13 (2.71) | 1.405 | +48 | +8.06 (2.68) | n/a |
| other | 5,690 | +1.92 (1.96) | 1.083 | +109 | -0.03 (-0.01) | +2.52 (2.23) |
| politics | 10 | +38.20 (2.97) | 6.701 | +4 | +26.12 (1.90) | +86.50 (57.67) |
| sports | 51,539 | +0.50 (1.53) | 1.021 | +259 | +0.67 (1.50) | +0.29 (0.60) |

Top 10 series on the earlier half: KXFIBAGAME, KXUCLCORNERS, KXAFCCLGAME, KXAFLGAME, KXLIIGAGAME, KXNCAAHOCKEYGAME, KXCONCACAFCCUPGAME, KXNFLMENTION, KXABAGAME, KXWBCSPREAD

**7 both sides, spread 5c+**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 65 | -2.23 (-0.46) | 0.837 | -1 | +0.17 (0.03) | -11.85 (-1.62) |
| economics | 1,988 | +0.27 (0.31) | 1.032 | +5 | +0.69 (0.69) | -0.41 (-0.27) |
| entertainment | 217 | +3.09 (2.16) | 1.603 | +7 | +2.15 (1.15) | +5.42 (2.92) |
| mentions | 2,581 | +3.36 (5.42) | 1.474 | +87 | +3.35 (5.37) | +3.97 (0.82) |
| other | 13,074 | +1.28 (3.75) | 1.126 | +167 | +0.85 (1.61) | +1.53 (3.45) |
| politics | 99 | +2.04 (0.56) | 1.264 | +2 | -1.20 (-0.28) | +4.33 (0.78) |
| sports | 58,670 | +2.74 (15.07) | 1.232 | +1,606 | +3.47 (13.55) | +1.81 (7.11) |

Top 10 series on the earlier half: KXNHLGAME, KXIPLTEAMTOTAL, KXBALGAME, KXWBCF5SPREAD, KXNATGASD, KXWTACHALLENGERMATCH, KXATPTOTALSETS, KXSERIEA1H, KXCOPADELREYADVANCE, KXNBAPTSLEADER

**8 NO after an hour with no trading**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 24 | +2.04 (0.21) | 1.137 | +0 | +3.50 (0.31) | -5.25 (-0.46) |
| economics | 463 | +2.67 (1.38) | 1.283 | +12 | +3.81 (1.46) | +1.25 (0.43) |
| entertainment | 65 | +4.60 (1.38) | 1.506 | +3 | +4.49 (1.26) | +6.25 (0.95) |
| mentions | 357 | +7.29 (3.36) | 1.585 | +26 | +7.60 (3.37) | +1.00 (0.18) |
| other | 5,498 | +0.42 (0.68) | 1.023 | +23 | -1.02 (-0.91) | +1.12 (1.54) |
| politics | 23 | -1.61 (-0.43) | 0.844 | -0 | -0.08 (-0.02) | -3.60 (-0.51) |
| sports | 53,514 | +0.18 (0.82) | 1.010 | +95 | +0.80 (2.80) | -0.47 (-1.46) |

Top 10 series on the earlier half: KXIPLTEAMTOTAL, KXMLBF5TOTAL, KXNCAABMENTION, KXFACUPTOTAL, KXNCAAMENTION, KXLIGUE11H, KXMLBF5SPREAD, KXBALLERLEAGUEGAME, KXATPSETWINNER, KXBOLPDIVGAME

**9 NO after an hour with trading**

| Category | Fills | ¢/contract (t) | Profit factor | Total $ | Earlier ¢ (t) | Later ¢ (t) |
|---|---:|---:|---:|---:|---:|---:|
| crypto | 49 | -5.24 (-1.01) | 0.580 | -3 | -9.19 (-1.41) | +1.56 (0.20) |
| economics | 1,912 | +3.17 (1.93) | 1.246 | +61 | +6.72 (2.34) | +0.75 (0.39) |
| entertainment | 181 | +3.46 (1.30) | 1.411 | +6 | +2.56 (0.78) | +5.96 (1.45) |
| mentions | 2,296 | +5.23 (3.67) | 1.343 | +120 | +5.19 (3.61) | +9.22 (0.98) |
| other | 15,872 | +1.62 (3.33) | 1.105 | +257 | +1.41 (1.47) | +1.66 (3.02) |
| politics | 66 | +3.44 (0.76) | 1.233 | +2 | +2.56 (0.41) | +5.09 (0.87) |
| sports | 120,646 | +0.63 (3.88) | 1.033 | +766 | +0.75 (3.57) | +0.49 (1.88) |

Top 10 series on the earlier half: KXUCLCORNERS, KXNCAAMB1HSPREAD, KXWBCRFI, KXWTI, KXCOPADOBRASILGAME, KXFIFASPREAD, KXCODMAP, KXUCLTCORNERS, KXUFCROUNDS, KXSIXNATIONSMATCH
