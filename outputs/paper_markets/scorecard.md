# Model-free "no" seller paper tests (other markets)

One $500 paper bankroll per series; rule in kalshi/paper_markets.py. Series marked +model use the NFL model as veto (markets/nfl/paper.py).

| Series | Orders | Open | Fill rate | Fills settled | ¢/contract | t | Bankroll |
|---|---:|---:|---:|---:|---:|---:|---:|
| KXITFMATCH | 1642 | 35 | 70% | 1126 | -0.63 | -1.03 | $376.92 |
| KXNASCARRACE | 243 | 0 | 71% | 172 | -0.42 | -0.73 | $498.39 |
| KXLIGAMXSPREAD | 242 | 0 | 57% | 139 | -4.98 | -0.96 | $460.65 |
| KXLALIGASPREAD | 158 | 0 | 46% | 72 | 0.03 | 0.0 | $490.28 |
| KXNFLANYTD | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS | 779 | 0 | 60% | 466 | -7.65 | -2.34 | $207.50 |
| KXCLUBFBTTS | 0 | 0 |  | 0 |  |  | $500.00 |
| KXUCLCORNERS | 64 | 0 | 38% | 24 | 29.08 | 3.24 | $589.71 |
| KXUFCMOF | 171 | 0 | 52% | 89 | -2.25 | -0.9 | $459.14 |
| KXNBAFTM | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMENTION | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNCAAMB1HSPREAD | 92 | 0 | 10% | 9 | 8.08 | 1.13 | $504.25 |
| KXNBA3D | 210 | 1 | 56% | 118 | 2.84 | 1.18 | $518.86 |
| KXNASCARTOP10 | 278 | 0 | 75% | 208 | 2.23 | 2.55 | $457.32 |
| KXNFLANYTD+model | 0 | 0 |  | 0 |  |  | $500.00 |
| KXNFLRECYDS+model | 687 | 0 | 51% | 349 | -3.91 | -0.93 | $319.19 |
| KXITFMATCH+no30 | 1301 | 37 | 73% | 928 | -1.2 | -1.23 | $418.70 |
