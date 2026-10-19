# Multilab

Works out its own chances for Serie A games, puts them next to Sportsbet's prices, and helps build multis. It's for fun at low stakes. It isn't tips.

## What it does

A GitHub Action runs `scripts/fetch_data.py` twice a week, Tuesday and Friday around 9am Adelaide. It pulls results from football-data.co.uk and Sportsbet prices from The Odds API, and saves them as JSON files in `data/serie-a/`.

`index.html` is the page. It reads those files in your browser, rates the teams, and does all the maths there. There's no server.

The Friday run also fetches the extra markets (both teams to score, double chance, draw no bet, alternate totals, correct score and a few others). Those cost Odds API credits. The Tuesday run doesn't fetch them.

## What's in here

```
index.html                  the page
scripts/fetch_data.py       the fetcher
scripts/team_names.json     fixes for clubs whose names differ between sites
scripts/check_bookmakers.py one-off check of which bookmakers return which markets
.github/workflows/          fetch-data.yml (the schedule), check-bookmakers.yml
data/serie-a/               written by the fetcher, don't edit
```

## Don't break it

- Leave the folders where they are. GitHub only runs workflows from `.github/workflows`, the script finds where to save from its own location, and Pages needs `index.html` at the top level.
- Never paste the Odds API key into a file. The repo is public. The key lives in Settings > Secrets and variables > Actions, named `ODDS_API_KEY`.
- Don't edit anything in `data/`. The next run overwrites it.
- Keep Settings > Actions > General > Workflow permissions on "Read and write". If it's not, the run works and then can't save anything.
- Mind the credits. The free plan is 500 a month and resets on the 1st. A run with extras uses about 70 to 140, depending on how many games Sportsbet has priced, so once a week is about right. The script stops fetching extras when 10 are left. `api_credits_left` in `meta.json` shows what's remaining.

## Things you have to do

**Every August:** change `SEASON_CODE` in `fetch-data.yml` (2627 becomes 2728). Change the default in `fetch_data.py` to match.

**A club's name doesn't match:** open `data/serie-a/meta.json`. `unknown_team_names` lists them. Add each one to `scripts/team_names.json` under `serie-a`, as `"name the odds site uses": "name in results"`, then run it again.

**Adding a league:** add it to `ENABLED_LEAGUES` at the top of `fetch_data.py`, run it, and check that league's `meta.json` before you trust anything. `check_bookmakers.py` is worth running too.

## When something looks wrong

Look at `data/serie-a/meta.json` first. `needs_attention` should be false. `sources` says whether results, history and odds loaded, and `extras` says how many games had prices for each market. A yellow warning on a run in the Actions tab is usually a team name or a source that failed.

**Runs stopped happening:** GitHub pauses scheduled runs on repos that go quiet. Go to Actions, pick Fetch Serie A data, and press Run workflow.

**The page won't load data:** check Pages is on (Settings > Pages, branch `main`, folder `/ (root)`) and that `data/serie-a/` has the files. Opening `index.html` straight from your computer doesn't work because the browser blocks it. The page shows a file picker instead.

**Odds failed:** most likely the month's credits are gone. They come back on the 1st. Results and history are free, so those still update.

## Running it by hand

Actions tab, pick the workflow, press Run workflow. Fetch Serie A data has a box for the extra markets. Leave it ticked if you're about to bet.

The page should be at https://kilrcola.github.io/MULTILAB/ and Settings > Pages shows the real address.
