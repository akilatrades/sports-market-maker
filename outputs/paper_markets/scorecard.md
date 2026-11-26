# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 3044 | 41 | 74% | 2216 | -1.19 | -3.05 | $176.63 |
| KXNASCARRACE | 295 | 0 | 72% | 213 | -0.22 | -0.45 | $499.77 |
| KXLIGAMXSPREAD | 327 | 0 | 56% | 184 | -2.96 | -0.7 | $471.87 |
| KXLALIGASPREAD | 214 | 0 | 48% | 103 | 0.24 | 0.05 | $494.51 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 1521 | 15 | 56% | 849 | -5.9 | -2.38 | $138.50 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 159 | 0 | 44% | 70 | 12.37 | 1.46 | $620.16 |
| KXUFCMOF | 318 | 0 | 44% | 141 | -1.44 | -0.68 | $455.36 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 744 | 1 | 19% | 139 | -7.24 | -1.53 | $381.46 |
| KXNBA3D | 526 | 5 | 50% | 260 | 2.95 | 1.9 | $550.95 |
| KXNASCARTOP10 | 367 | 0 | 73% | 268 | 2.8 | 1.82 | $470.28 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 1246 | 15 | 49% | 607 | -4.57 | -1.49 | $267.85 |
| KXITFMATCH+no30 | 2518 | 32 | 75% | 1869 | -1.44 | -2.16 | $244.42 |
