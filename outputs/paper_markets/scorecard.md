# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1055 | 22 | 70% | 726 | -0.14 | -0.19 | $330.45 |
| KXNASCARRACE | 182 | 0 | 71% | 130 | -0.18 | -0.24 | $498.83 |
| KXLIGAMXSPREAD | 194 | 0 | 60% | 117 | -5.44 | -0.92 | $464.61 |
| KXLALIGASPREAD | 121 | 4 | 39% | 46 | 1.38 | 0.15 | $506.12 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 477 | 0 | 58% | 277 | -8.48 | -2.11 | $281.63 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 73 | 1 | 68% | 49 | 2.82 | 0.69 | $506.17 |
| KXNASCARTOP10 | 186 | 0 | 75% | 140 | 1.59 | 1.81 | $479.59 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 449 | 0 | 49% | 221 | -5.73 | -1.16 | $350.04 |
| KXITFMATCH+no30 | 799 | 16 | 74% | 583 | 0.07 | 0.06 | $508.05 |
