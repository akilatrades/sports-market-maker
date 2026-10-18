# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 156 | 26 | 83% | 108 | -1.71 | -1.14 | $395.76 |
| KXNASCARRACE | 53 | 21 | 56% | 18 | 0.77 | 0.0 | $500.94 |
| KXLIGAMXSPREAD | 56 | 6 | 58% | 29 | -3.36 | -0.3 | $492.42 |
| KXLALIGASPREAD | 32 | 0 | 50% | 16 | 17.08 | 3.19 | $519.23 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 42 | 28 | 0% | 0 |  |  | $500.00 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXITFMATCH+no30 | 33 | 18 | 93% | 14 | 10.08 | 2.43 | $515.99 |
