# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1581 | 10 | 70% | 1098 | -0.62 | -0.99 | $393.88 |
| KXNASCARRACE | 243 | 16 | 70% | 160 | -0.44 | -0.7 | $498.21 |
| KXLIGAMXSPREAD | 238 | 8 | 58% | 134 | -5.82 | -1.1 | $455.78 |
| KXLALIGASPREAD | 158 | 4 | 44% | 68 | -0.69 | -0.1 | $487.58 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 670 | 35 | 57% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 13 | 0 | 31% | 4 | 10.52 | None | $500.97 |
| KXNBA3D | 158 | 4 | 63% | 97 | 2.49 | 0.85 | $514.01 |
| KXNASCARTOP10 | 278 | 29 | 75% | 186 | 1.74 | 2.19 | $446.24 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 598 | 34 | 45% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1249 | 7 | 73% | 911 | -1.06 | -1.07 | $434.39 |
