#!/usr/bin/env python3
"""
Serie A data fetcher for the multi builder.

Runs on GitHub Actions (or your PC) and writes JSON files the web app reads:
  data/serie-a/results.json  - every result this season + closing market odds
  data/serie-a/odds.json     - upcoming matches with Sportsbet odds
  data/serie-a/meta.json     - when it last ran, what worked, unknown team names

Uses only the Python standard library, so nothing needs installing.
If one source fails, the others are still saved, and the old file is kept.
"""
import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

# ---- Settings ---------------------------------------------------------------
SEASON_CODE = os.environ.get("SEASON_CODE", "2627")   # 2026/27. Change each August.
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
BOOKMAKER = os.environ.get("BOOKMAKER", "sportsbet")

RESULTS_URL = f"https://www.football-data.co.uk/mmz4281/{SEASON_CODE}/I1.csv"
ODDS_URL = (
    "https://api.the-odds-api.com/v4/sports/soccer_italy_serie_a/odds/"
    "?apiKey={key}&bookmakers={book}&markets=h2h,totals&oddsFormat=decimal"
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
OUT_DIR = os.path.join(REPO_ROOT, "data", "serie-a")
NAMES_FILE = os.path.join(SCRIPT_DIR, "team_names.json")

# Closing-odds columns worth keeping from football-data.co.uk (used if present)
ODDS_COLUMNS = {
    "avg_home": "AvgCH", "avg_draw": "AvgCD", "avg_away": "AvgCA",
    "avg_over25": "AvgC>2.5", "avg_under25": "AvgC<2.5",
    "pin_home": "PSCH", "pin_draw": "PSCD", "pin_away": "PSCA",
}

unknown_names = set()


# ---- Helpers ----------------------------------------------------------------
def load_name_map():
    try:
        with open(NAMES_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def canon(name, name_map, known):
    """Turn any source's team name into one standard name."""
    name = name.strip()
    if name in name_map:
        return name_map[name]
    if known and name not in known:
        unknown_names.add(name)
    return name


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "serie-a-multi-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read(), dict(resp.headers)


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def save(filename, data):
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


# ---- Sources ----------------------------------------------------------------
def parse_results_csv(text, name_map):
    matches = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("HomeTeam") or row.get("FTHG") in (None, ""):
            continue
        d = row.get("Date", "")
        try:
            day = datetime.strptime(d, "%d/%m/%Y").date().isoformat()
        except ValueError:
            day = d
        closing = {k: num(row.get(col)) for k, col in ODDS_COLUMNS.items() if num(row.get(col))}
        matches.append({
            "date": day,
            "home": canon(row["HomeTeam"], name_map, None),
            "away": canon(row["AwayTeam"], name_map, None),
            "hg": int(row["FTHG"]), "ag": int(row["FTAG"]),
            "ht_hg": int(row["HTHG"]) if row.get("HTHG") else None,
            "ht_ag": int(row["HTAG"]) if row.get("HTAG") else None,
            "closing_odds": closing,
        })
    return matches


def fetch_results(name_map):
    raw, _ = get(RESULTS_URL)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return parse_results_csv(text, name_map)


def fetch_odds(name_map, known):
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY secret is not set")
    raw, headers = get(ODDS_URL.format(key=ODDS_API_KEY, book=BOOKMAKER))
    events = json.loads(raw)
    out = []
    for ev in events:
        game = {
            "kickoff_utc": ev.get("commence_time"),
            "home": canon(ev["home_team"], name_map, known),
            "away": canon(ev["away_team"], name_map, known),
            "h2h": {}, "totals": [],
        }
        for book in ev.get("bookmakers", []):
            for market in book.get("markets", []):
                if market["key"] == "h2h":
                    for o in market["outcomes"]:
                        if o["name"] == ev["home_team"]:
                            game["h2h"]["home"] = o["price"]
                        elif o["name"] == ev["away_team"]:
                            game["h2h"]["away"] = o["price"]
                        else:
                            game["h2h"]["draw"] = o["price"]
                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        game["totals"].append(
                            {"side": o["name"].lower(), "line": o.get("point"), "price": o["price"]}
                        )
        out.append(game)
    remaining = headers.get("x-requests-remaining") or headers.get("X-Requests-Remaining")
    return out, remaining


# ---- Main -------------------------------------------------------------------
def main():
    name_map = load_name_map()
    meta = {
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": SEASON_CODE,
        "sources": {},
    }

    known = set()
    try:
        results = fetch_results(name_map)
        save("results.json", results)
        known = {m["home"] for m in results} | {m["away"] for m in results}
        meta["sources"]["results"] = {"ok": True, "matches": len(results)}
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
        meta["sources"]["results"] = {"ok": False, "error": str(e)}

    try:
        odds, remaining = fetch_odds(name_map, known)
        save("odds.json", odds)
        meta["sources"]["odds"] = {"ok": True, "games": len(odds), "api_credits_left": remaining}
    except (urllib.error.URLError, OSError, ValueError, KeyError, RuntimeError) as e:
        meta["sources"]["odds"] = {"ok": False, "error": str(e)}

    meta["unknown_team_names"] = sorted(unknown_names)
    save("meta.json", meta)

    for src, info in meta["sources"].items():
        print(f"{src}: {'OK' if info['ok'] else 'FAILED - ' + info['error']}")
    if unknown_names:
        print("Add these to scripts/team_names.json:", ", ".join(sorted(unknown_names)))


if __name__ == "__main__":
    main()
