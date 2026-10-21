# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 575 | 36 | 69% | 374 | 0.04 | 0.04 | $372.02 |
| KXNASCARRACE | 77 | 0 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 93 | 0 | 59% | 55 | -5.71 | -0.69 | $473.24 |
| KXLALIGASPREAD | 59 | 0 | 42% | 25 | 0.92 | 0.08 | $496.36 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 250 | 0 | 56% | 140 | -8.91 | -1.72 | $359.44 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 32 | 25% | 8 | 36.25 | 1.89 | $550.42 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 7 | 0 | 86% | 6 | 4.8 | 3.63 | $501.44 |
| KXNASCARTOP10 | 77 | 0 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 231 | 0 | 48% | 111 | -9.15 | -1.21 | $384.34 |
| KXITFMATCH+no30 | 389 | 38 | 73% | 257 | 2.25 | 1.37 | $550.62 |
