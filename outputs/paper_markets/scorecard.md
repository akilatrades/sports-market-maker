# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1543 | 10 | 71% | 1085 | -0.62 | -0.99 | $375.79 |
| KXNASCARRACE | 227 | 0 | 70% | 160 | -0.44 | -0.7 | $498.21 |
| KXLIGAMXSPREAD | 230 | 0 | 58% | 134 | -5.82 | -1.1 | $455.78 |
| KXLALIGASPREAD | 147 | 0 | 44% | 65 | 0.77 | 0.11 | $497.33 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 618 | 0 | 58% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 155 | 1 | 63% | 97 | 2.49 | 0.85 | $514.01 |
| KXNASCARTOP10 | 249 | 0 | 75% | 186 | 1.74 | 2.19 | $446.24 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 547 | 0 | 46% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1224 | 9 | 74% | 897 | -0.96 | -0.96 | $440.43 |
