# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 888 | 11 | 72% | 631 | 0.17 | 0.21 | $382.41 |
| KXNASCARRACE | 105 | 23 | 73% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 149 | 0 | 61% | 91 | -5.88 | -0.84 | $471.11 |
| KXLALIGASPREAD | 86 | 9 | 38% | 29 | -0.63 | -0.06 | $496.68 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 323 | 0 | 54% | 174 | -8.55 | -2.07 | $340.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 32 | 44% | 37 | -5.54 | -1.51 | $473.90 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 46 | 1 | 67% | 30 | 2.19 | 0.34 | $505.32 |
| KXNASCARTOP10 | 110 | 24 | 65% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 289 | 0 | 46% | 133 | -6.45 | -1.02 | $386.95 |
| KXITFMATCH+no30 | 661 | 12 | 76% | 494 | 0.4 | 0.32 | $528.40 |
