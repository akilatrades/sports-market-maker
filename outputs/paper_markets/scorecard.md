# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 698 | 11 | 68% | 465 | -0.06 | -0.06 | $370.44 |
| KXNASCARRACE | 77 | 0 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 133 | 0 | 62% | 82 | -7.78 | -1.02 | $465.70 |
| KXLALIGASPREAD | 63 | 0 | 43% | 27 | -2.42 | -0.22 | $493.67 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 284 | 34 | 56% | 140 | -8.91 | -1.72 | $359.44 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 26 | 4 | 68% | 15 | 6.38 | 3.95 | $504.97 |
| KXNASCARTOP10 | 77 | 0 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 264 | 33 | 48% | 111 | -9.15 | -1.21 | $384.34 |
| KXITFMATCH+no30 | 501 | 11 | 71% | 350 | 0.15 | 0.1 | $527.93 |
