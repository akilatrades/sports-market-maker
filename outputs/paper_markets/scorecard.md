# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1936 | 3 | 70% | 1352 | -0.9 | -1.63 | $300.96 |
| KXNASCARRACE | 271 | 14 | 72% | 184 | -0.33 | -0.61 | $498.63 |
| KXLIGAMXSPREAD | 266 | 12 | 58% | 148 | -3.9 | -0.79 | $466.92 |
| KXLALIGASPREAD | 177 | 4 | 46% | 80 | 1.15 | 0.19 | $494.98 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 851 | 0 | 59% | 500 | -6.23 | -1.89 | $215.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 128 | 0 | 50% | 64 | 11.42 | 1.31 | $606.90 |
| KXUFCMOF | 206 | 35 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 139 | 23 | 16% | 18 | -7.38 | -0.79 | $479.54 |
| KXNBA3D | 260 | 10 | 60% | 150 | 2.06 | 1.01 | $515.68 |
| KXNASCARTOP10 | 327 | 21 | 75% | 229 | 1.83 | 2.07 | $458.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 726 | 0 | 49% | 356 | -4.43 | -1.06 | $313.16 |
| KXITFMATCH+no30 | 1576 | 7 | 72% | 1135 | -1.48 | -1.69 | $374.52 |
