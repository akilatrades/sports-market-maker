# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1605 | 26 | 70% | 1104 | -0.54 | -0.86 | $387.67 |
| KXNASCARRACE | 243 | 0 | 71% | 172 | -0.42 | -0.73 | $498.39 |
| KXLIGAMXSPREAD | 242 | 0 | 57% | 139 | -4.98 | -0.96 | $460.65 |
| KXLALIGASPREAD | 158 | 0 | 46% | 72 | 0.03 | 0.0 | $490.28 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 707 | 0 | 60% | 421 | -9.28 | -2.86 | $206.27 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 13 | 0 | 31% | 4 | 10.52 | None | $500.97 |
| KXNBA3D | 160 | 1 | 64% | 102 | 2.61 | 0.94 | $515.26 |
| KXNASCARTOP10 | 278 | 0 | 75% | 208 | 2.23 | 2.55 | $457.32 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 632 | 0 | 49% | 311 | -5.38 | -1.19 | $316.02 |
| KXITFMATCH+no30 | 1266 | 21 | 73% | 914 | -1.16 | -1.18 | $428.34 |
