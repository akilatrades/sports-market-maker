# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 238 | 26 | 75% | 158 | -0.09 | -0.07 | $421.37 |
| KXNASCARRACE | 77 | 22 | 71% | 39 | 1.34 | 2.54 | $501.82 |
| KXLIGAMXSPREAD | 56 | 0 | 62% | 35 | -10.8 | -0.95 | $468.68 |
| KXLALIGASPREAD | 55 | 5 | 40% | 20 | 11.66 | 1.81 | $516.62 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 97 | 34 | 32% | 20 | -28.23 | -0.0 | $469.72 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 77 | 34 | 65% | 28 | 4.14 | None | $484.93 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 89 | 36 | 4% | 2 | -24.42 | -0.0 | $495.28 |
| KXITFMATCH+no30 | 103 | 21 | 80% | 66 | 2.62 | 0.83 | $515.20 |
