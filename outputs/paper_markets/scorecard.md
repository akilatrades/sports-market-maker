# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 328 | 8 | 76% | 242 | 0.2 | 0.17 | $400.91 |
| KXNASCARRACE | 77 | 0 | 78% | 60 | 0.74 | 1.11 | $502.33 |
| KXLIGAMXSPREAD | 64 | 0 | 64% | 41 | -7.22 | -0.69 | $473.50 |
| KXLALIGASPREAD | 59 | 4 | 45% | 25 | 0.92 | 0.08 | $496.36 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 208 | 33 | 51% | 90 | -11.17 | -1.42 | $393.14 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUFCMOF | 60 | 0 | 57% | 34 | -9.05 | -2.71 | $466.38 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNBA3D | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNASCARTOP10 | 77 | 0 | 73% | 56 | 1.49 | 0.56 | $479.39 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 200 | 32 | 43% | 73 | -13.52 | -1.19 | $394.73 |
| KXITFMATCH+no30 | 171 | 10 | 80% | 128 | 3.1 | 1.44 | $527.51 |
