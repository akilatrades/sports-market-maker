# Spread maker backtest by game phase (SIMULATED, in-sample, exploratory)

| Rule | Fills | ¢/contract (t) | Earlier / later half ¢ | Share of profit |
|---|---:|---:|---:|---:|
| all hours (v1) | 11,263 | 8.45 (21.48) | 9.1 / 7.81 | 100% |
| skip the last hour | 5,930 | 10.27 (18.2) | 10.93 / 9.61 | 64% |
| skip the last hour and known in-game | 5,864 | 10.39 (18.33) | 11.2 / 9.61 | 64% |
| ticker start known, pregame only | 2,285 | 9.87 (9.93) | 12.24 / 7.52 | 24% |
| skip the last hour, no financial series | 5,761 | 10.29 (17.86) | 11.11 / 9.47 | 62% |
