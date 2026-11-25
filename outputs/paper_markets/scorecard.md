# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 3024 | 25 | 74% | 2216 | -1.19 | -3.05 | $176.63 |
| KXNASCARRACE | 295 | 0 | 72% | 213 | -0.22 | -0.45 | $499.77 |
| KXLIGAMXSPREAD | 327 | 4 | 57% | 183 | -3.11 | -0.73 | $470.45 |
| KXLALIGASPREAD | 214 | 0 | 48% | 103 | 0.24 | 0.05 | $494.51 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 1521 | 41 | 57% | 849 | -5.9 | -2.38 | $138.50 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 159 | 0 | 44% | 70 | 12.37 | 1.46 | $620.16 |
| KXUFCMOF | 318 | 0 | 44% | 141 | -1.44 | -0.68 | $455.36 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 744 | 35 | 19% | 132 | -5.66 | -1.2 | $402.24 |
| KXNBA3D | 526 | 13 | 50% | 255 | 3.28 | 2.12 | $554.26 |
| KXNASCARTOP10 | 367 | 0 | 73% | 268 | 2.8 | 1.82 | $470.28 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 1246 | 36 | 50% | 607 | -4.57 | -1.49 | $267.85 |
| KXITFMATCH+no30 | 2504 | 20 | 75% | 1869 | -1.44 | -2.16 | $244.42 |
