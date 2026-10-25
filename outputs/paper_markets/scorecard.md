# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 988 | 6 | 71% | 693 | -0.11 | -0.13 | $349.87 |
| KXNASCARRACE | 182 | 33 | 66% | 99 | 0.6 | 1.58 | $503.25 |
| KXLIGAMXSPREAD | 169 | 4 | 59% | 98 | -4.39 | -0.67 | $476.62 |
| KXLALIGASPREAD | 116 | 6 | 37% | 41 | -0.71 | -0.07 | $500.01 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 418 | 35 | 53% | 203 | -7.01 | -1.89 | $339.20 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 66 | 8 | 69% | 40 | 1.86 | 0.37 | $502.78 |
| KXNASCARTOP10 | 186 | 34 | 70% | 107 | 1.68 | 1.42 | $477.10 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 380 | 36 | 46% | 158 | -4.42 | -0.83 | $407.92 |
| KXITFMATCH+no30 | 746 | 8 | 75% | 553 | -0.08 | -0.06 | $506.49 |
