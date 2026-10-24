# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 888 | 5 | 72% | 637 | 0.17 | 0.21 | $380.31 |
| KXNASCARRACE | 130 | 25 | 79% | 83 | 0.65 | 1.4 | $502.79 |
| KXLIGAMXSPREAD | 157 | 8 | 61% | 91 | -5.88 | -0.84 | $471.11 |
| KXLALIGASPREAD | 89 | 5 | 37% | 31 | 0.37 | 0.04 | $498.36 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 323 | 0 | 54% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 12 | 43% | 45 | -4.49 | -1.4 | $465.66 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 55 | 10 | 67% | 30 | 2.19 | 0.34 | $505.32 |
| KXNASCARTOP10 | 144 | 58 | 65% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 289 | 0 | 46% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 661 | 7 | 76% | 499 | 0.42 | 0.34 | $531.29 |
