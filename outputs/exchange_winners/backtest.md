# Game winners on Novig and ProphetX: backtest

Historical and simulated: every bet is assumed to fill at the shown
price. Not live results, and not a forecast. The plan and the pass
bar were written first (RESEARCH_LOG.md, 2026-11-22).

Pull: stopped: this run's cap of 3000 credits. 238 of 1413 days done, 3000 credits in all.

## Games behind the tables

| Sport | Days pulled | Games priced | With a result | No result found | Ties |
|---|---:|---:|---:|---:|---:|
| NFL | 20 | 112 | 111 | 0 | 1 |
| College football | 20 | 268 | 268 | 0 | 0 |
| NBA | 39 | 244 | 243 | 1 | 0 |
| College basketball (men) | 35 | 1226 | 1202 | 24 | 0 |
| MLB | 36 | 352 | 350 | 2 | 0 |

## What a bet with no opinion costs (every team, every game)

| Venue | Sport | Games | Width | Before fees | After fees |
|---|---|---:|---:|---:|---:|
| Novig | All | 2105 | 1.1% | -0.8¢ | -0.8¢ |
| Novig | NFL | 110 | 0.5% | -0.3¢ | -0.3¢ |
| Novig | College football | 267 | 0.7% | -0.4¢ | -0.4¢ |
| Novig | NBA | 242 | 0.6% | -0.3¢ | -0.3¢ |
| Novig | College basketball (men) | 1136 | 2.2% | -1.2¢ | -1.2¢ |
| Novig | MLB | 350 | 0.6% | -0.3¢ | -0.3¢ |
| ProphetX | All | 2080 | 1.1% | -0.7¢ | -1.1¢ |
| ProphetX | NFL | 111 | 0.5% | -0.3¢ | -0.7¢ |
| ProphetX | College football | 266 | 0.8% | -0.4¢ | -0.8¢ |
| ProphetX | NBA | 242 | 0.5% | -0.3¢ | -0.7¢ |
| ProphetX | College basketball (men) | 1111 | 1.8% | -1.0¢ | -1.4¢ |
| ProphetX | MLB | 350 | 0.6% | -0.3¢ | -0.8¢ |
| Kalshi | All | 1451 | 1.1% | -0.6¢ | -2.0¢ |
| Kalshi | NFL | 65 | 1.1% | -0.5¢ | -2.0¢ |
| Kalshi | College football | 160 | 1.0% | -0.5¢ | -1.8¢ |
| Kalshi | NBA | 183 | 1.1% | -0.7¢ | -2.1¢ |
| Kalshi | College basketball (men) | 739 | 1.1% | -0.7¢ | -2.0¢ |
| Kalshi | MLB | 304 | 1.0% | -0.6¢ | -2.3¢ |
| Polymarket US | All | 21 | 0.9% | -0.4¢ |  |
| Polymarket US | NFL | 1 | 0.2% | -0.1¢ |  |
| Polymarket US | NBA | 16 | 1.0% | -0.5¢ |  |
| Polymarket US | MLB | 4 | 0.5% | -0.2¢ |  |

## Value: buying a team priced under the sportsbooks' fair price

| Venue | Rule | Group | Bets | Avg price | Won | After fees | t |
|---|---|---|---:|---:|---:|---:|---:|
| Novig | value 2 | All | 22 | 10¢ | 18.2% | +8.6¢ | +1.2 |
| Novig | value 2 | NFL | 1 | 10¢ | 0.0% | +nan¢ |  |
| Novig | value 2 | College football | 4 | 6¢ | 25.0% | +18.9¢ | +0.7 |
| Novig | value 2 | NBA | 3 | 8¢ | 0.0% | -7.7¢ | -3.2 |
| Novig | value 2 | College basketball (men) | 14 | 11¢ | 21.4% | +10.5¢ | +1.1 |
| Novig | value 2 | First Half | 10 | 10¢ | 10.0% | +0.4¢ | +0.0 |
| Novig | value 2 | Second Half | 12 | 10¢ | 25.0% | +15.5¢ | +1.4 |
| ProphetX | value 2 | All | 20 | 13¢ | 10.0% | -2.9¢ | -0.4 |
| ProphetX | value 2 | NFL | 1 | 11¢ | 0.0% | +nan¢ |  |
| ProphetX | value 2 | NBA | 4 | 8¢ | 0.0% | -7.9¢ | -3.0 |
| ProphetX | value 2 | College basketball (men) | 15 | 14¢ | 13.3% | -1.1¢ | -0.1 |
| ProphetX | value 2 | First Half | 9 | 12¢ | 0.0% | -11.8¢ | -4.7 |
| ProphetX | value 2 | Second Half | 11 | 14¢ | 18.2% | +4.3¢ | +0.4 |

## Verdict against the bar

- Novig, value 2: **does not pass** (22 bets; positive in 0 of 0 sports with 30+ bets).
- Novig, value 4: **does not pass** (0 bets; positive in 0 of 0 sports with 30+ bets).
- ProphetX, value 2: **does not pass** (20 bets; positive in 0 of 0 sports with 30+ bets).
- ProphetX, value 4: **does not pass** (0 bets; positive in 0 of 0 sports with 30+ bets).

## Exploratory: every team, by the price paid

| Venue | Price | Bets | Won | After fees | t |
|---|---|---:|---:|---:|---:|
| Novig | 0-30c | 819 | 16.2% | -1.8¢ | -1.4 |
| Novig | 30-45c | 796 | 37.4% | -0.9¢ | -0.5 |
| Novig | 45-55c | 866 | 50.3% | +0.3¢ | +0.4 |
| Novig | 55-70c | 842 | 59.6% | -2.0¢ | -1.2 |
| Novig | 70-100c | 887 | 83.0% | +0.3¢ | +0.2 |
| ProphetX | 0-30c | 810 | 16.4% | -1.8¢ | -1.4 |
| ProphetX | 30-45c | 799 | 37.8% | -1.1¢ | -0.6 |
| ProphetX | 45-55c | 842 | 49.8% | -0.7¢ | -1.3 |
| ProphetX | 55-70c | 858 | 60.4% | -1.8¢ | -1.1 |
| ProphetX | 70-100c | 851 | 83.2% | -0.1¢ | -0.1 |
