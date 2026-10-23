# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 814 | 11 | 70% | 564 | 0.09 | 0.1 | $395.17 |
| KXNASCARRACE | 105 | 28 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 141 | 8 | 62% | 82 | -7.78 | -1.02 | $465.70 |
| KXLALIGASPREAD | 67 | 0 | 43% | 29 | -0.63 | -0.06 | $496.68 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 323 | 0 | 54% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 42 | 16 | 69% | 18 | 8.6 | 3.09 | $509.87 |
| KXNASCARTOP10 | 110 | 33 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 289 | 0 | 46% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 604 | 13 | 74% | 439 | 0.13 | 0.1 | $524.64 |
