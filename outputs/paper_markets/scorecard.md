# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1519 | 23 | 70% | 1053 | -0.59 | -0.92 | $342.90 |
| KXNASCARRACE | 200 | 0 | 70% | 139 | -0.39 | -0.53 | $497.58 |
| KXLIGAMXSPREAD | 210 | 0 | 61% | 128 | -4.52 | -0.83 | $468.45 |
| KXLALIGASPREAD | 136 | 11 | 41% | 51 | 1.52 | 0.18 | $508.22 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 618 | 0 | 58% | 359 | -9.62 | -2.94 | $213.83 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 116 | 0 | 49% | 57 | -3.91 | -1.43 | $462.82 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 138 | 2 | 66% | 90 | 2.01 | 0.64 | $510.81 |
| KXNASCARTOP10 | 211 | 0 | 75% | 159 | 2.03 | 2.27 | $461.90 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 547 | 0 | 46% | 253 | -3.35 | -0.77 | $361.02 |
| KXITFMATCH+no30 | 1208 | 21 | 73% | 872 | -0.84 | -0.85 | $435.41 |
