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
- **Team names don't match:** `meta.json` lists any `unknown_team_names`. Add each one to `team_names.json` like `"Name from odds site": "Name in results"`, then rerun.
- **Runs stopped happening:** GitHub can pause schedules on quiet repos. Press **Run workflow** to wake it up.

## Each season

In August, change `SEASON_CODE` in `fetch-data.yml` (for example, `"2728"` for 2027/28).

## Reading the data in your app

Because the files are on the same site as your app, the browser allows it:

```js
const results = await (await fetch('data/serie-a/results.json')).json();
```

## Still manual (for now)

xG, BTTS and correct score prices, and team news. xG from Understat or FotMob can be added later as a separate step that's allowed to fail without breaking the rest.
