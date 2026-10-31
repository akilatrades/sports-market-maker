# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1533 | 17 | 71% | 1070 | -0.56 | -0.89 | $339.46 |
| KXNASCARRACE | 215 | 15 | 70% | 139 | -0.39 | -0.53 | $497.58 |
| KXLIGAMXSPREAD | 214 | 4 | 61% | 128 | -4.52 | -0.83 | $468.45 |
| KXLALIGASPREAD | 142 | 8 | 40% | 53 | 0.75 | 0.09 | $504.76 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 618 | 0 | 58% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 148 | 32 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 147 | 10 | 66% | 90 | 2.01 | 0.64 | $510.81 |
| KXNASCARTOP10 | 234 | 23 | 75% | 159 | 2.03 | 2.27 | $461.90 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 547 | 0 | 46% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1217 | 14 | 74% | 887 | -0.77 | -0.79 | $441.47 |
