# Dry-run order logs

Output of the GitHub *nba trade (dry run)* workflow; `nfl/` holds the
*nfl trade (dry run)* equivalent. These are orders the research trader
**would** place, with the model's probability, the sportsbook probability,
the edge and the risk decision. No order here was sent to an exchange.

- `orders.csv`: every order the dry-run trader built, with the risk decision.
- `last_run.json`: summary of the last run.
- `scorecard.md`: running summary of the logged orders.

The funded bots' real orders are recorded privately on the server. Their stop
switches are `/home/trader/prod-nba-auto/KILL` and
`/home/trader/prod-nfl-auto/KILL`, or the owner-only Go live / Stop button
([deploy/GO_LIVE_BUTTON.md](../../deploy/GO_LIVE_BUTTON.md)).
