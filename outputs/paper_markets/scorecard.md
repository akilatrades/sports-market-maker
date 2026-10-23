# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 804 | 4 | 70% | 561 | 0.04 | 0.05 | $394.28 |
| KXNASCARRACE | 103 | 26 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 133 | 0 | 62% | 82 | -7.78 | -1.02 | $465.70 |
| KXLALIGASPREAD | 67 | 4 | 43% | 27 | -2.42 | -0.22 | $493.67 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 323 | 0 | 54% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 39 | 13 | 69% | 18 | 8.6 | 3.09 | $509.87 |
| KXNASCARTOP10 | 109 | 32 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 289 | 0 | 46% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 595 | 7 | 74% | 436 | 0.07 | 0.05 | $522.37 |
