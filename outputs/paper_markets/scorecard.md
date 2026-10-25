# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 988 | 2 | 71% | 697 | -0.1 | -0.13 | $347.01 |
| KXNASCARRACE | 182 | 31 | 66% | 99 | 0.6 | 1.58 | $503.25 |
| KXLIGAMXSPREAD | 181 | 16 | 59% | 98 | -4.39 | -0.67 | $476.62 |
| KXLALIGASPREAD | 117 | 6 | 37% | 41 | -0.71 | -0.07 | $500.01 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 475 | 69 | 54% | 218 | -9.06 | -2.39 | $300.84 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 69 | 11 | 69% | 40 | 1.86 | 0.37 | $502.78 |
| KXNASCARTOP10 | 186 | 33 | 70% | 107 | 1.68 | 1.42 | $477.10 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 444 | 68 | 45% | 170 | -5.1 | -1.02 | $381.13 |
| KXITFMATCH+no30 | 746 | 5 | 75% | 556 | -0.06 | -0.05 | $506.98 |
