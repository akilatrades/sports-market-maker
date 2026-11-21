# Pick'em app lines

`nba_latest.csv` holds the lines PrizePicks and Underdog post on tonight's NBA
player props, for the "Pick'em apps" tab of the player-pool page
(`research/nba_player_pool_dashboard.html`). `nba_<day>.csv.gz` keeps every
pull of that day.

Written by `research/pickem_lines.py` (workflow "pick'em app lines"), about
four times a day. Only each app's line and the sides it offers are kept, not
the feed's indicative prices. Publishing these two apps' lines is the owner's
decision of 21 November 2026; everything else from the odds feed is still
published only as the sportsbooks' de-vigged consensus.

These files are for the page. The live bots never read them, and they must
never be merged into `outputs/books/`.
