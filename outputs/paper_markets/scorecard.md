# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 988 | 35 | 71% | 672 | 0.06 | 0.07 | $370.19 |
| KXNASCARRACE | 130 | 0 | 76% | 99 | 0.6 | 1.58 | $503.25 |
| KXLIGAMXSPREAD | 165 | 0 | 59% | 98 | -4.39 | -0.67 | $476.62 |
| KXLALIGASPREAD | 107 | 12 | 38% | 36 | 5.18 | 0.54 | $514.40 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 383 | 36 | 50% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 58 | 0 | 69% | 40 | 1.86 | 0.37 | $502.78 |
| KXNASCARTOP10 | 144 | 0 | 74% | 107 | 1.68 | 1.42 | $477.10 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 344 | 33 | 43% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 746 | 31 | 75% | 537 | 0.27 | 0.23 | $519.47 |
