# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1864 | 40 | 69% | 1260 | -0.74 | -1.28 | $312.51 |
| KXNASCARRACE | 243 | 0 | 71% | 172 | -0.42 | -0.73 | $498.39 |
| KXLIGAMXSPREAD | 242 | 0 | 57% | 139 | -4.98 | -0.96 | $460.65 |
| KXLALIGASPREAD | 158 | 0 | 46% | 72 | 0.03 | 0.0 | $490.28 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 851 | 0 | 59% | 500 | -6.23 | -1.89 | $215.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 128 | 0 | 50% | 64 | 11.42 | 1.31 | $606.90 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 101 | 0 | 12% | 12 | 2.95 | 0.42 | $497.22 |
| KXNBA3D | 232 | 2 | 59% | 135 | 1.87 | 0.82 | $512.88 |
| KXNASCARTOP10 | 278 | 0 | 75% | 208 | 2.23 | 2.55 | $457.32 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 726 | 0 | 49% | 356 | -4.43 | -1.06 | $313.16 |
| KXITFMATCH+no30 | 1513 | 43 | 71% | 1050 | -1.21 | -1.32 | $397.70 |
