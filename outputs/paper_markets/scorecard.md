# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 238 | 15 | 76% | 169 | 0.34 | 0.27 | $440.29 |
| KXNASCARRACE | 77 | 22 | 71% | 39 | 1.34 | 2.54 | $501.82 |
| KXLIGAMXSPREAD | 60 | 4 | 62% | 35 | -10.8 | -0.95 | $468.68 |
| KXLALIGASPREAD | 55 | 0 | 45% | 25 | 0.92 | 0.08 | $496.36 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 165 | 68 | 43% | 42 | -14.1 | -1.54 | $457.99 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 77 | 34 | 65% | 28 | 4.14 | None | $484.93 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 158 | 69 | 21% | 19 | -36.24 | -11.58 | $446.42 |
| KXITFMATCH+no30 | 103 | 12 | 82% | 75 | 2.29 | 0.83 | $520.79 |
