# Multilab

Works out its own chances for football games (Serie A and the Premier League so far), puts them next to Sportsbet's prices, and helps build multis. It's for fun at low stakes. It isn't tips.

## What it does

A GitHub Action runs `scripts/fetch_data.py` twice a week, Tuesday and Friday around 9am Adelaide. It pulls results from football-data.co.uk and Sportsbet prices from The Odds API, and saves them as JSON files in `data/<league>/`, one folder per league.

`index.html` is the page. It reads those files in your browser, rates the teams, and does all the maths there. There's no server. Each league has a button at the top of the page that switches it on or off in the view, and one slip can hold legs from both leagues. Those buttons only change what you see. They don't change what gets fetched.

The Friday run also fetches the extra markets (both teams to score, double chance, draw no bet, alternate totals, correct score and a few others). Those cost Odds API credits. The Tuesday run doesn't fetch them.

## What's in here

```
index.html                  the page
scripts/fetch_data.py       the fetcher
scripts/team_names.json     fixes for clubs whose names differ between sites
scripts/check_bookmakers.py one-off check of which bookmakers return which markets
.github/workflows/          fetch-data.yml (the schedule), check-bookmakers.yml
data/<league>/              written by the fetcher, don't edit (serie-a, premier-league)
data/leagues.json           the list of leagues the page shows, written by the fetcher
```

## Don't break it

- Leave the folders where they are. GitHub only runs workflows from `.github/workflows`, the script finds where to save from its own location, and Pages needs `index.html` at the top level.
- Never paste the Odds API key into a file. The repo is public. The key lives in Settings > Secrets and variables > Actions, named `ODDS_API_KEY`.
- Don't edit anything in `data/`. The next run overwrites it.
- Keep Settings > Actions > General > Workflow permissions on "Read and write". If it's not, the run works and then can't save anything.
- Mind the credits. The free plan is 500 a month and resets on the 1st. A run with extras uses about 70 to 140 credits per league, depending on how many games Sportsbet has priced, so two leagues every Friday is more than the free plan covers. To spend less, start a manual run and pick one league in the "Leagues to fetch" box. The script stops fetching extras when 10 are left. `api_credits_left` in `meta.json` shows what's remaining.

## Things you have to do

**Every August:** change `SEASON_CODE` in `fetch-data.yml` (2627 becomes 2728). Change the default in `fetch_data.py` to match.

**A club's name doesn't match:** open that league's `meta.json` (for example `data/premier-league/meta.json`). `unknown_team_names` lists them. Add each one to `scripts/team_names.json` under that league, as `"name the odds site uses": "name in results"`, then run it again.

**Adding a league:** add it to `ENABLED_LEAGUES` at the top of `fetch_data.py`, add its name to the "Leagues to fetch" list in `fetch-data.yml` if you want to run it on its own, then run it and check that league's `meta.json` before you trust anything. The page picks the new league up by itself from `data/leagues.json`. The settings (the goal squeeze, the stretch and the trust slider) were tuned on Serie A, so check them on the new league's data before relying on the defaults.

## When something looks wrong

Look at the league's `data/<league>/meta.json` first. `needs_attention` should be false. `sources` says whether results, history and odds loaded, and `extras` says how many games had prices for each market. A yellow warning on a run in the Actions tab is usually a team name or a source that failed.

**Runs stopped happening:** GitHub pauses scheduled runs on repos that go quiet. Go to Actions, pick Fetch football data, and press Run workflow.

**The page won't load data:** check Pages is on (Settings > Pages, branch `main`, folder `/ (root)`) and that `data/<league>/` has the files. Opening `index.html` straight from your computer doesn't work because the browser blocks it. The page shows a file picker instead.

**Odds failed:** most likely the month's credits are gone. They come back on the 1st. Results and history are free, so those still update.

## Running it by hand

Actions tab, pick the workflow, press Run workflow. Fetch football data has a box for the extra markets (leave it ticked if you're about to bet) and a "Leagues to fetch" choice. A scheduled run always fetches every enabled league.

The page should be at https://kilrcola.github.io/MULTILAB/ and Settings > Pages shows the real address.
