# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 591 | 25 | 69% | 393 | 0.13 | 0.13 | $367.92 |
| KXNASCARRACE | 77 | 0 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 93 | 0 | 59% | 55 | -5.71 | -0.69 | $473.24 |
| KXLALIGASPREAD | 63 | 4 | 42% | 25 | 0.92 | 0.08 | $496.36 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 250 | 0 | 56% | 140 | -8.91 | -1.72 | $359.44 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 16 | 17% | 8 | 36.25 | 1.89 | $550.42 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 16 | 9 | 86% | 6 | 4.8 | 3.63 | $501.44 |
| KXNASCARTOP10 | 77 | 0 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 231 | 0 | 48% | 111 | -9.15 | -1.21 | $384.34 |
| KXITFMATCH+no30 | 402 | 23 | 74% | 279 | 1.54 | 0.95 | $530.00 |
