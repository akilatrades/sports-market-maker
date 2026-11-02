# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1581 | 4 | 70% | 1102 | -0.54 | -0.86 | $389.78 |
| KXNASCARRACE | 243 | 12 | 69% | 160 | -0.44 | -0.7 | $498.21 |
| KXLIGAMXSPREAD | 242 | 6 | 57% | 134 | -5.82 | -1.1 | $455.78 |
| KXLALIGASPREAD | 158 | 0 | 46% | 72 | 0.03 | 0.0 | $490.28 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 707 | 37 | 57% | 385 | -8.15 | -2.47 | $241.73 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 13 | 0 | 31% | 4 | 10.52 | None | $500.97 |
| KXNBA3D | 160 | 5 | 63% | 98 | 2.54 | 0.88 | $514.40 |
| KXNASCARTOP10 | 278 | 22 | 73% | 186 | 1.74 | 2.19 | $446.24 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 632 | 34 | 46% | 277 | -2.77 | -0.69 | $375.43 |
| KXITFMATCH+no30 | 1249 | 6 | 73% | 912 | -1.16 | -1.18 | $430.46 |
