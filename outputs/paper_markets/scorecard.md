# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 2943 | 10 | 74% | 2176 | -1.16 | -2.95 | $196.68 |
| KXNASCARRACE | 295 | 0 | 72% | 213 | -0.22 | -0.45 | $499.77 |
| KXLIGAMXSPREAD | 323 | 1 | 57% | 182 | -3.2 | -0.75 | $469.77 |
| KXLALIGASPREAD | 214 | 0 | 48% | 103 | 0.24 | 0.05 | $494.51 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 1435 | 40 | 56% | 786 | -5.67 | -2.19 | $157.51 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 128 | 0 | 50% | 64 | 11.42 | 1.31 | $606.90 |
| KXUFCMOF | 318 | 0 | 44% | 141 | -1.44 | -0.68 | $455.36 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 607 | 0 | 17% | 104 | -6.06 | -1.11 | $427.97 |
| KXNBA3D | 510 | 7 | 49% | 248 | 3.13 | 1.97 | $549.53 |
| KXNASCARTOP10 | 367 | 0 | 73% | 268 | 2.8 | 1.82 | $470.28 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 1198 | 33 | 49% | 570 | -4.31 | -1.34 | $285.11 |
| KXITFMATCH+no30 | 2442 | 12 | 76% | 1837 | -1.44 | -2.15 | $250.16 |
