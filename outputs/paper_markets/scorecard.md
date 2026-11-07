# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1916 | 27 | 70% | 1313 | -0.85 | -1.5 | $297.68 |
| KXNASCARRACE | 257 | 0 | 72% | 184 | -0.33 | -0.61 | $498.63 |
| KXLIGAMXSPREAD | 254 | 0 | 58% | 148 | -3.9 | -0.79 | $466.92 |
| KXLALIGASPREAD | 162 | 0 | 45% | 73 | 0.11 | 0.02 | $490.57 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 851 | 0 | 59% | 500 | -6.23 | -1.89 | $215.81 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 128 | 0 | 50% | 64 | 11.42 | 1.31 | $606.90 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 116 | 0 | 16% | 18 | -7.38 | -0.79 | $479.54 |
| KXNBA3D | 252 | 5 | 60% | 147 | 1.97 | 0.94 | $514.71 |
| KXNASCARTOP10 | 306 | 0 | 75% | 229 | 1.83 | 2.07 | $458.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 726 | 0 | 49% | 356 | -4.43 | -1.06 | $313.16 |
| KXITFMATCH+no30 | 1558 | 28 | 72% | 1100 | -1.33 | -1.49 | $381.71 |
