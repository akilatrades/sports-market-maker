# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1345 | 42 | 68% | 888 | -0.7 | -0.99 | $258.24 |
| KXNASCARRACE | 182 | 0 | 71% | 130 | -0.18 | -0.24 | $498.83 |
| KXLIGAMXSPREAD | 198 | 4 | 60% | 117 | -5.44 | -0.92 | $464.61 |
| KXLALIGASPREAD | 121 | 0 | 40% | 48 | 0.01 | 0.0 | $502.25 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 546 | 0 | 60% | 325 | -9.16 | -2.58 | $241.42 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 109 | 15 | 67% | 63 | 3.56 | 1.11 | $510.48 |
| KXNASCARTOP10 | 186 | 0 | 75% | 140 | 1.59 | 1.81 | $479.59 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 493 | 0 | 48% | 238 | -4.08 | -0.87 | $357.39 |
| KXITFMATCH+no30 | 1060 | 40 | 71% | 725 | -0.82 | -0.75 | $450.18 |
