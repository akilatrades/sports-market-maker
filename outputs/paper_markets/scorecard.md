# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1002 | 15 | 71% | 698 | -0.17 | -0.21 | $343.68 |
| KXNASCARRACE | 182 | 0 | 71% | 130 | -0.18 | -0.24 | $498.83 |
| KXLIGAMXSPREAD | 194 | 20 | 56% | 98 | -4.39 | -0.67 | $476.62 |
| KXLALIGASPREAD | 117 | 0 | 39% | 46 | 1.38 | 0.15 | $506.12 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 477 | 32 | 55% | 246 | -10.95 | -2.74 | $269.99 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 72 | 9 | 68% | 43 | 2.3 | 0.49 | $504.00 |
| KXNASCARTOP10 | 186 | 0 | 75% | 140 | 1.59 | 1.81 | $479.59 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 449 | 33 | 45% | 189 | -8.33 | -1.52 | $340.87 |
| KXITFMATCH+no30 | 758 | 16 | 75% | 557 | -0.14 | -0.12 | $501.76 |
