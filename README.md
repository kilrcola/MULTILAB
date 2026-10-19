# Serie A data fetcher – setup

Twice a week (Tue and Fri, 9am Adelaide), GitHub runs a script that grabs Serie A results and Sportsbet odds and saves them as JSON files in your repo. Your app reads those files.

## One-time setup (about 10 minutes)

1. **Get a free odds key.** Sign up at the-odds-api.com and copy your API key.
2. **Copy these files into your repo**, keeping the folders exactly as they are:
   - `.github/workflows/fetch-data.yml`
   - `scripts/fetch_data.py`
   - `scripts/team_names.json`

   Note: the `.github` folder starts with a dot, so some computers hide it. If you upload through the GitHub website, create the file at that path and paste the contents in.
3. **Store the key as a secret** (never paste it into the code). In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Name it `ODDS_API_KEY` and paste the key.
4. **Run it once by hand.** Go to the **Actions** tab, click **Fetch Serie A data**, then **Run workflow**. After a minute or so it should show a green tick.
5. **Check the results.** A new `data/serie-a/` folder should appear with `results.json`, `odds.json` and `meta.json`.

## If something goes wrong

- **Red cross on the push step:** go to **Settings → Actions → General → Workflow permissions**, choose **Read and write permissions**, and save.
- **Odds failed:** open `meta.json` to see the error. Usually the secret name is misspelt, or you've used up the month's free credits. Each run costs only a couple.
- **Yellow warning on a run:** the script found something to check, usually a team name it couldn't match. Click the run to read it, or open `meta.json` and look for `needs_attention`.
- **Team names don't match:** most are matched automatically ("AC Milan" becomes "Milan"). Anything left over is listed under `unknown_team_names` in `meta.json`. Add it to `team_names.json` under the right league, like `"Name from odds site": "Name in results"`, then rerun.
- **Runs stopped happening:** GitHub can pause schedules on quiet repos. Press **Run workflow** to wake it up.

## Adding another league (checklist)

1. In `scripts/fetch_data.py`, add the league to `ENABLED_LEAGUES` near the top. The options are `premier-league`, `la-liga`, `bundesliga` and `ligue-1`.
2. Press **Run workflow** in the Actions tab.
3. **Check names before trusting any odds.** Open `data/<league>/meta.json` and look at:
   - `unknown_team_names`: add each one to that league's section of `team_names.json`.
   - `auto_matched_names`: quickly confirm every pairing is right.
   - `name_problems`: this flags things like 19 teams found when 20 were expected.
4. Rerun until there are no yellow warnings and `needs_attention` is `false`.

Each extra league uses a couple more free Odds API credits per run.

## Each season

In August, change `SEASON_CODE` in `fetch-data.yml` (for example, `"2728"` for 2027/28).

## Reading the data in your app

Because the files are on the same site as your app, the browser allows it:

```js
const results = await (await fetch('data/serie-a/results.json')).json();
```

## Still manual (for now)

xG, BTTS and correct score prices, and team news. xG from Understat or FotMob can be added later as a separate step that's allowed to fail without breaking the rest.
