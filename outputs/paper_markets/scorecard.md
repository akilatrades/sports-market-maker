# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1535 | 13 | 71% | 1075 | -0.63 | -0.99 | $375.83 |
| KXNASCARRACE | 227 | 23 | 68% | 139 | -0.39 | -0.53 | $497.58 |
| KXLIGAMXSPREAD | 230 | 16 | 60% | 128 | -4.52 | -0.83 | $468.45 |
| KXLALIGASPREAD | 147 | 7 | 41% | 58 | 1.56 | 0.19 | $512.17 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 618 | 0 | 58% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 42 | 44% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 155 | 12 | 63% | 90 | 2.01 | 0.64 | $510.81 |
| KXNASCARTOP10 | 249 | 32 | 73% | 159 | 2.03 | 2.27 | $461.90 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 547 | 0 | 46% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1219 | 12 | 74% | 890 | -1.05 | -1.05 | $430.02 |
