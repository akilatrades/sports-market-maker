# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1467 | 29 | 70% | 1002 | -0.66 | -1.0 | $258.20 |
| KXNASCARRACE | 182 | 0 | 71% | 130 | -0.18 | -0.24 | $498.83 |
| KXLIGAMXSPREAD | 198 | 0 | 61% | 121 | -4.7 | -0.82 | $468.68 |
| KXLALIGASPREAD | 125 | 4 | 40% | 48 | 0.01 | 0.0 | $502.25 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 618 | 0 | 58% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 125 | 12 | 67% | 76 | 3.4 | 1.23 | $513.48 |
| KXNASCARTOP10 | 186 | 0 | 75% | 140 | 1.59 | 1.81 | $479.59 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 547 | 0 | 46% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1167 | 24 | 73% | 832 | -0.71 | -0.7 | $445.82 |
