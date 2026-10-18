# NFL worker memory repair — 2026-10-18

The production service log contained `Failed with result 'oom-kill'`, repeated
`status=9/KILL`, and a startup timeout. An active timer does not prove successful
scans: check the timestamp in the private `last_scan.json` and completion logs.
The OOM message confirms memory exhaustion; it does not identify the server's
total RAM, a configured service limit, or every other process using memory.

The repair removes analysis-library imports from the private account dashboard,
loads the NFL schedule without the unused player-history table, reduces saved
projection files in chunks, and limits repeated injury checks to fixture weeks
actually present in the candidate markets. The worker prints its input stages,
peak resident memory after input loading, and a completion marker. These logs
are unbuffered under systemd.

Offline measurements using the seven saved ladders and NFL data at commit
`36f6012a29e655ab8a5c5bcf601f7293a075f77a`:

| Measurement | Before | After |
| --- | ---: | ---: |
| Dashboard import peak RSS | 59.8 MiB | 20.5 MiB |
| Schedule, player/injury and ladder load peak RSS | 116.6 MiB | 73.7 MiB |
| 100 injury checks for one week | 3.80 seconds | 0.052 seconds |
| Injury records examined per check | 23,476 | 125 |

These are separate local process measurements, not measurements of total
Droplet usage or a guarantee that the Droplet has enough remaining memory.

Validation also found 108 latest projection keys with conflicting probabilities
at the same timestamp. Those keys are excluded rather than choosing by sort
order or reviving an older estimate. Every one of the 34,770 retained rows
matches the previous loader's result. A later, unambiguous projection can make
an excluded key eligible again. No thresholds, order sizes, or risk limits were
increased, and no journal or kill-switch file is reset.

## Owner-run update

Run in the DigitalOcean server console:

```bash
curl -fsS https://raw.githubusercontent.com/akilatrades/sports-market-maker/main/deploy/update_nfl_dashboard.sh -o /tmp/update_nfl_dashboard.sh && sudo bash /tmp/update_nfl_dashboard.sh
```

The updater pauses the timer, releases the old read-only dashboard process,
waits for an existing worker to finish, pulls the code, installs the units, and
restarts the dashboard. It restores the NFL timer only if it was previously
active. It never directly starts a trading pass or arms a stopped timer.
The existing private journal, environment, and kill switch remain in place.

Then follow the existing timer's next run:

```bash
sudo journalctl -u market-maker-prod-nfl-auto.service -n 12 -f -o cat
```

Look for `NFL WORKER: completed` and a fresh `NFL SCAN` timestamp. A completed
scan can still report no eligible candidates or budget blocks. Completion does
not imply an order, a fill, or a profit. Ctrl+C closes the log viewer only.
If OOM recurs, use the printed `free -h`, service `MemoryMax`, and stage logs to
distinguish host memory pressure from a service memory limit before changing
server capacity. Do not increase trading limits to address a process crash.
