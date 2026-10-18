# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 226 | 32 | 75% | 146 | -0.06 | -0.04 | $430.47 |
| KXNASCARRACE | 64 | 11 | 74% | 39 | 1.34 | 2.54 | $501.82 |
| KXLIGAMXSPREAD | 56 | 0 | 62% | 35 | -10.8 | -0.95 | $468.68 |
| KXLALIGASPREAD | 52 | 8 | 41% | 18 | 16.33 | 3.5 | $520.26 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 67 | 35 | 0% | 0 |  |  | $500.00 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 47 | 33 | 0% | 0 |  |  | $500.00 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 65 | 34 | 0% | 0 |  |  | $500.00 |
| KXITFMATCH+no30 | 95 | 30 | 82% | 53 | 3.55 | 0.99 | $526.00 |
