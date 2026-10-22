# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 696 | 38 | 67% | 443 | -0.03 | -0.03 | $371.47 |
| KXNASCARRACE | 77 | 0 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 133 | 0 | 62% | 82 | -7.78 | -1.02 | $465.70 |
| KXLALIGASPREAD | 63 | 0 | 43% | 27 | -2.42 | -0.22 | $493.67 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 250 | 0 | 56% | 140 | -8.91 | -1.72 | $359.44 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 22 | 0 | 68% | 15 | 6.38 | 3.95 | $504.97 |
| KXNASCARTOP10 | 77 | 0 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 231 | 0 | 48% | 111 | -9.15 | -1.21 | $384.34 |
| KXITFMATCH+no30 | 500 | 39 | 71% | 327 | 1.1 | 0.73 | $554.38 |
