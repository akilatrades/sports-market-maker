# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1892 | 7 | 69% | 1309 | -0.85 | -1.5 | $295.50 |
| KXNASCARRACE | 257 | 14 | 71% | 172 | -0.42 | -0.73 | $498.39 |
| KXLIGAMXSPREAD | 254 | 12 | 57% | 139 | -4.98 | -0.96 | $460.65 |
| KXLALIGASPREAD | 162 | 0 | 45% | 73 | 0.11 | 0.02 | $490.57 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 851 | 0 | 59% | 500 | -6.23 | -1.89 | $215.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 128 | 0 | 50% | 64 | 11.42 | 1.31 | $606.90 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 116 | 11 | 11% | 12 | 2.95 | 0.42 | $497.22 |
| KXNBA3D | 252 | 22 | 59% | 135 | 1.87 | 0.82 | $512.88 |
| KXNASCARTOP10 | 306 | 28 | 75% | 208 | 2.23 | 2.55 | $457.32 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 726 | 0 | 49% | 356 | -4.43 | -1.06 | $313.16 |
| KXITFMATCH+no30 | 1537 | 11 | 72% | 1096 | -1.34 | -1.49 | $378.63 |
