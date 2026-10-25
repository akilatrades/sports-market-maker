# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 926 | 37 | 72% | 643 | 0.17 | 0.21 | $376.98 |
| KXNASCARRACE | 130 | 0 | 76% | 99 | 0.6 | 1.58 | $503.25 |
| KXLIGAMXSPREAD | 165 | 5 | 59% | 94 | -5.17 | -0.76 | $473.84 |
| KXLALIGASPREAD | 89 | 0 | 40% | 36 | 5.18 | 0.54 | $514.40 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 323 | 0 | 54% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 58 | 3 | 69% | 38 | 2.95 | 0.57 | $507.64 |
| KXNASCARTOP10 | 144 | 0 | 74% | 107 | 1.68 | 1.42 | $477.10 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 289 | 0 | 46% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 695 | 37 | 76% | 503 | 0.47 | 0.39 | $532.52 |
