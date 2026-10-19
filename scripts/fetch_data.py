#!/usr/bin/env python3
"""
MULTILAB data fetcher.

For each league switched on below, it writes:
  data/<league>/results.json  - every result this season + closing market odds
  data/<league>/odds.json     - upcoming matches with Sportsbet odds
  data/<league>/meta.json     - when it ran, what worked, and any name problems

Team names are matched automatically where possible ("AC Milan" -> "Milan").
Anything it can't match safely is flagged in meta.json AND as a yellow warning
on the GitHub Actions run, so a new league never fails silently.

Standard library only, so nothing needs installing.
"""
import csv
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---- Switch leagues on here --------------------------------------------------
# Each league costs a couple of Odds API credits per run.
ENABLED_LEAGUES = ["serie-a"]
# e.g. ENABLED_LEAGUES = ["serie-a", "premier-league", "la-liga", "bundesliga", "ligue-1"]

LEAGUES = {
    "serie-a":        {"csv": "I1",  "odds": "soccer_italy_serie_a",       "teams": 20},
    "premier-league": {"csv": "E0",  "odds": "soccer_epl",                 "teams": 20},
    "la-liga":        {"csv": "SP1", "odds": "soccer_spain_la_liga",       "teams": 20},
    "bundesliga":     {"csv": "D1",  "odds": "soccer_germany_bundesliga",  "teams": 18},
    "ligue-1":        {"csv": "F1",  "odds": "soccer_france_ligue_one",    "teams": 18},
}

SEASON_CODE = os.environ.get("SEASON_CODE", "2627")   # 2026/27. Change each August.
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
BOOKMAKER = os.environ.get("BOOKMAKER", "sportsbet")

RESULTS_URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
ODDS_URL = (
    "https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    "?apiKey={key}&bookmakers={book}&markets=h2h,totals&oddsFormat=decimal"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
NAMES_FILE = os.path.join(SCRIPT_DIR, "team_names.json")

ODDS_COLUMNS = {
    "avg_home": "AvgCH", "avg_draw": "AvgCD", "avg_away": "AvgCA",
    "avg_over25": "AvgC>2.5", "avg_under25": "AvgC<2.5",
    "pin_home": "PSCH", "pin_draw": "PSCD", "pin_away": "PSCA",
}

# Club-name filler words ignored when matching names automatically
FILLER = {"ac", "acf", "as", "ss", "ssc", "us", "fc", "cfc", "bc", "afc", "sc",
          "cf", "calcio", "club", "football"}


# ---- Name matching -----------------------------------------------------------
def tokens(name):
    words = re.findall(r"[a-z]+|\d+", name.lower())
    return [w for w in words if w not in FILLER and not w.isdigit()]


class NameMatcher:
    """Maps any source's team name onto the names used in results.json."""

    def __init__(self, manual_map, known):
        self.manual = manual_map
        self.known = set(known)
        self.unknown = set()
        self.auto = {}

    def __call__(self, name):
        name = name.strip()
        if name in self.manual:
            return self.manual[name]
        if not self.known or name in self.known:
            return name
        t = tokens(name)
        exact = [k for k in self.known if tokens(k) == t]
        if len(exact) == 1:
            self.auto[name] = exact[0]
            return exact[0]
        subset = [k for k in self.known if tokens(k) and set(tokens(k)) <= set(t)]
        if len(subset) == 1:
            self.auto[name] = subset[0]
            return subset[0]
        self.unknown.add(name)   # ambiguous or no match: needs a manual line
        return name


def load_name_map(league):
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {k: v for k, v in data.get(league, {}).items() if not k.startswith("_")}
    except (OSError, json.JSONDecodeError):
        return {}


# ---- Helpers -----------------------------------------------------------------
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "multilab/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), dict(resp.headers)


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save(league, filename, data):
    out_dir = os.path.join(REPO_ROOT, "data", league)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def warn(title, message):
    # Shows as a yellow warning on the GitHub Actions run summary
    print(f"::warning title={title}::{message}")


# ---- Sources -----------------------------------------------------------------
def parse_results_csv(text):
    matches = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("HomeTeam") or row.get("FTHG") in (None, ""):
            continue
        d = row.get("Date", "")
        try:
            day = datetime.strptime(d, "%d/%m/%Y").date().isoformat()
        except ValueError:
            day = d
        closing = {k: num(row.get(c)) for k, c in ODDS_COLUMNS.items() if num(row.get(c))}
        matches.append({
            "date": day,
            "home": row["HomeTeam"].strip(), "away": row["AwayTeam"].strip(),
            "hg": int(row["FTHG"]), "ag": int(row["FTAG"]),
            "ht_hg": int(row["HTHG"]) if row.get("HTHG") else None,
            "ht_ag": int(row["HTAG"]) if row.get("HTAG") else None,
            "closing_odds": closing,
        })
    return matches


def fetch_results(cfg):
    raw, _ = get(RESULTS_URL.format(season=SEASON_CODE, code=cfg["csv"]))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return parse_results_csv(text)


def parse_odds(events, match):
    out = []
    for ev in events:
        game = {"kickoff_utc": ev.get("commence_time"),
                "home": match(ev["home_team"]), "away": match(ev["away_team"]),
                "h2h": {}, "totals": []}
        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                if market["key"] == "h2h":
                    for o in market["outcomes"]:
                        side = ("home" if o["name"] == ev["home_team"]
                                else "away" if o["name"] == ev["away_team"] else "draw")
                        game["h2h"][side] = o["price"]
                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        game["totals"].append({"side": o["name"].lower(),
                                               "line": o.get("point"), "price": o["price"]})
        out.append(game)
    return out


def fetch_odds(cfg, match):
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY secret is not set")
    raw, headers = get(ODDS_URL.format(sport=cfg["odds"], key=ODDS_API_KEY, book=BOOKMAKER))
    remaining = headers.get("x-requests-remaining") or headers.get("X-Requests-Remaining")
    return parse_odds(json.loads(raw), match), remaining


# ---- Checks ------------------------------------------------------------------
def team_checks(league, cfg, results, matcher):
    problems = []
    teams = {m["home"] for m in results} | {m["away"] for m in results}
    # After a full round, every club should have appeared exactly once by name
    if len(results) >= cfg["teams"] // 2 and len(teams) != cfg["teams"]:
        problems.append(f"results show {len(teams)} team names, expected {cfg['teams']}")
    if matcher.unknown:
        problems.append("odds names not matched: " + ", ".join(sorted(matcher.unknown)))
    for p in problems:
        warn(f"{league} team names", p)
    return problems


# ---- Main --------------------------------------------------------------------
def run_league(league):
    cfg = LEAGUES[league]
    meta = {"fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "season": SEASON_CODE, "sources": {}}

    results = []
    try:
        results = fetch_results(cfg)
        save(league, "results.json", results)
        meta["sources"]["results"] = {"ok": True, "matches": len(results)}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        meta["sources"]["results"] = {"ok": False, "error": str(e)}
        warn(f"{league} results", str(e))

    known = {m["home"] for m in results} | {m["away"] for m in results}
    matcher = NameMatcher(load_name_map(league), known)
    try:
        odds, remaining = fetch_odds(cfg, matcher)
        save(league, "odds.json", odds)
        meta["sources"]["odds"] = {"ok": True, "games": len(odds), "api_credits_left": remaining}
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as e:
        meta["sources"]["odds"] = {"ok": False, "error": str(e)}
        warn(f"{league} odds", str(e))

    meta["name_problems"] = team_checks(league, cfg, results, matcher)
    meta["unknown_team_names"] = sorted(matcher.unknown)
    meta["auto_matched_names"] = matcher.auto      # worth a glance the first time
    meta["needs_attention"] = bool(meta["name_problems"]) or not all(
        s["ok"] for s in meta["sources"].values())
    save(league, "meta.json", meta)

    status = "NEEDS ATTENTION" if meta["needs_attention"] else "OK"
    print(f"[{league}] {status}")
    for src, info in meta["sources"].items():
        print(f"  {src}: {'OK' if info['ok'] else 'FAILED - ' + info['error']}")
    for odds_name, result_name in sorted(matcher.auto.items()):
        print(f"  auto-matched: {odds_name} -> {result_name}")


def main():
    for league in ENABLED_LEAGUES:
        if league not in LEAGUES:
            warn("Config", f"unknown league '{league}' in ENABLED_LEAGUES")
            continue
        run_league(league)


if __name__ == "__main__":
    main()
