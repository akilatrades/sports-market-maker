# Contributing

Thanks for helping. New here? Read [docs/START_HERE.md](docs/START_HERE.md)
first: it covers what the project does and how it is laid out. Using an AI
assistant? [CLAUDE.md](CLAUDE.md) gives it the same rules; they apply to its
work as much as yours.

## How changes get in

1. Fork the repository, clone your fork and make a branch.
2. Make the change and run the checks below.
3. Open a pull request into `main` and say what changed and why.
4. The owner reviews every pull request (`.github/CODEOWNERS`). A merge does
   not change the live bots by itself; the owner deploys to the server
   separately, so changes under `live/`, `kalshi/`, `markets/`, `tools/`,
   `deploy/` and `.github/` get the closest review.

Write access is not given out, because write access to this repository
amounts to access to the server and the funded account
([why](deploy/GITHUB_ACCESS.md#why-not-write-access)).

## Checks to run before opening a pull request

```bash
pip install -r requirements.txt ruff==0.11.13
ruff check .
ruff format --check .
pytest -q
```

GitHub runs the same checks on your pull request.

## Rules

- **No secrets, ever.** No API keys, passwords, private keys, server
  addresses or account numbers in code, tests, logs or screenshots. If one
  slips in, say so right away; deleting it in a later commit is not enough.
- **No licensed raw data.** Raw sportsbook (Odds API) and Databento files
  stay out of the repository. Derived, aggregated results are fine.
- **Write the test down before running it.** Research ideas go into
  [RESEARCH_LOG.md](RESEARCH_LOG.md) with the rule and the pass/fail bar
  *before* looking at results, so a good backtest cannot be cherry-picked.
- **Risk limits move only on purpose.** Changes to `live/`, `deploy/` or
  `.github/` need a clear reason in the pull request, and any change to a
  risk limit must say the old value, the new value and why.
- **Dated documents stay as written.** Files with a date in the name are a
  record of what was known that day; add a new document instead of editing.
