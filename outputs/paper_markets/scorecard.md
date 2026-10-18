# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 217 | 37 | 73% | 132 | 0.02 | 0.02 | $442.82 |
| KXNASCARRACE | 53 | 0 | 74% | 39 | 1.34 | 2.54 | $501.82 |
| KXLIGAMXSPREAD | 56 | 0 | 62% | 35 | -10.8 | -0.95 | $468.68 |
| KXLALIGASPREAD | 49 | 11 | 42% | 16 | 17.08 | 3.19 | $519.23 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 65 | 33 | 0% | 0 |  |  | $500.00 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 42 | 28 | 0% | 0 |  |  | $500.00 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 64 | 33 | 0% | 0 |  |  | $500.00 |
| KXITFMATCH+no30 | 89 | 34 | 78% | 43 | 3.35 | 0.79 | $521.83 |
