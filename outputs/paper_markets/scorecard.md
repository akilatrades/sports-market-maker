# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1083 | 29 | 71% | 744 | -0.1 | -0.13 | $361.13 |
| KXNASCARRACE | 182 | 0 | 71% | 130 | -0.18 | -0.24 | $498.83 |
| KXLIGAMXSPREAD | 194 | 0 | 60% | 117 | -5.44 | -0.92 | $464.61 |
| KXLALIGASPREAD | 121 | 0 | 40% | 48 | 0.01 | 0.0 | $502.25 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 546 | 69 | 58% | 277 | -8.48 | -2.11 | $281.63 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 79 | 6 | 67% | 49 | 2.82 | 0.69 | $506.17 |
| KXNASCARTOP10 | 186 | 0 | 75% | 140 | 1.59 | 1.81 | $479.59 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 493 | 44 | 49% | 221 | -5.73 | -1.16 | $350.04 |
| KXITFMATCH+no30 | 815 | 20 | 74% | 592 | -0.02 | -0.02 | $504.24 |
