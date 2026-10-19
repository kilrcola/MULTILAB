#!/usr/bin/env python3
"""
MULTILAB data fetcher.

For each league switched on below, it writes:
  data/<league>/results.json  - every result this season + closing market odds + shots, corners, cards
  data/<league>/history.json  - the previous seasons (default 3), same fields; completed seasons are fetched once
  data/<league>/odds.json     - upcoming games: prices per bookmaker + extra markets
  data/<league>/meta.json     - when it ran, what worked, name problems, extra-market coverage

odds.json layout (one entry per game):
  id, kickoff_utc, home, away (our names), home_api, away_api (the odds site's own names),
  books:  { "sportsbet": {"h2h": {...}, "totals": [...]}, "playup": {...}, ... }
  extras: { "sportsbet": { "btts": {...}, "double_chance": {...}, ... } }

Extra markets (BTTS, double chance, ...) cost credits per game, so they only run
when FETCH_EXTRAS=true, and only for upcoming games Sportsbet has already priced.

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
from datetime import datetime, timedelta, timezone

# ---- Switch leagues on here --------------------------------------------------
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
HISTORY_SEASONS = int(os.environ.get("HISTORY_SEASONS", "3"))   # how many past seasons the page uses as priors
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

# Bookmakers asked for in the standard call (up to 10 count as one region).
# Sportsbet is the one you bet with. PlayUp and TABtouch were the only AU books
# returning over/under goals in the 19 Oct 2026 bookmaker check, so they act as
# reference prices for totals.
BOOKMAKERS = os.environ.get("BOOKMAKERS", "sportsbet,playup,tabtouch")
PRIMARY = os.environ.get("PRIMARY_BOOKMAKER", "sportsbet")


def env_flag(name, default="false"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


# ---- Extra markets (one request per game per market, ~1 credit each) ---------
FETCH_EXTRAS = env_flag("FETCH_EXTRAS")
EXTRA_MARKETS = ["btts", "double_chance", "draw_no_bet", "alternate_totals",
                 "team_totals", "correct_score", "alternate_spreads"]
EXTRAS_WITHIN_DAYS = int(os.environ.get("EXTRAS_WITHIN_DAYS", "7"))
STOP_EXTRAS_AT_CREDITS = int(os.environ.get("STOP_EXTRAS_AT_CREDITS", "10"))  # keeps a small reserve

RESULTS_URL = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
ODDS_URL = ("https://api.the-odds-api.com/v4/sports/{sport}/odds/"
            "?apiKey={key}&bookmakers={books}&markets=h2h,totals&oddsFormat=decimal")
EVENT_ODDS_URL = ("https://api.the-odds-api.com/v4/sports/{sport}/events/{event}/odds"
                  "?apiKey={key}&bookmakers={book}&markets={market}&oddsFormat=decimal")

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
        return resp.read(), {k.lower(): v for k, v in resp.headers.items()}


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def save(league, filename, data):
    out_dir = os.path.join(REPO_ROOT, "data", league)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def warn(title, message):
    print(f"::warning title={title}::{message}")      # yellow warning on the run


def notice(title, message):
    print(f"::notice title={title}::{message}")       # blue note on the run


# ---- Results -----------------------------------------------------------------
def int_or_none(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_date(d):
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(d, fmt).date().isoformat()
        except ValueError:
            pass
    return d


# football-data.co.uk column -> short key in our JSON
STAT_COLUMNS = {"hs": "HS", "as": "AS", "hst": "HST", "ast": "AST", "hc": "HC", "ac": "AC",
                "hy": "HY", "ay": "AY", "hr": "HR", "ar": "AR"}


def parse_results_csv(text):
    matches = []
    for row in csv.DictReader(io.StringIO(text)):
        if not row.get("HomeTeam") or row.get("FTHG") in (None, ""):
            continue
        closing = {k: num(row.get(c)) for k, c in ODDS_COLUMNS.items() if num(row.get(c))}
        m = {
            "date": parse_date(row.get("Date", "")),
            "home": row["HomeTeam"].strip(), "away": row["AwayTeam"].strip(),
            "hg": int(row["FTHG"]), "ag": int(row["FTAG"]),
            "ht_hg": int_or_none(row.get("HTHG")), "ht_ag": int_or_none(row.get("HTAG")),
        }
        for key, col in STAT_COLUMNS.items():
            m[key] = int_or_none(row.get(col))
        m["closing_odds"] = closing
        matches.append(m)
    return matches


def prev_season(code, back=1):
    a, b = int(code[:2]), int(code[2:])
    return f"{(a - back) % 100:02d}{(b - back) % 100:02d}"


def fetch_results(cfg, season=None):
    raw, _ = get(RESULTS_URL.format(season=season or SEASON_CODE, code=cfg["csv"]))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    return parse_results_csv(text)


def load_json(league, filename, default):
    try:
        with open(os.path.join(REPO_ROOT, "data", league, filename), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def fetch_history(league, cfg):
    """Past seasons for ratings priors. A finished season never changes, so it is fetched once."""
    history = load_json(league, "history.json", {})
    wanted = [prev_season(SEASON_CODE, k) for k in range(1, HISTORY_SEASONS + 1)]
    history = {k: v for k, v in history.items() if k in wanted}
    errors = {}
    for code in wanted:
        if code in history:
            continue
        try:
            history[code] = fetch_results(cfg, code)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            errors[code] = str(e)
    save(league, "history.json", history)
    return {"ok": bool(history), "seasons": sorted(history), "missing": sorted(errors),
            "errors": errors, "matches": sum(len(v) for v in history.values())}


# ---- Odds --------------------------------------------------------------------
def parse_odds(events, match):
    games = []
    for ev in events:
        game = {"id": ev.get("id"), "kickoff_utc": ev.get("commence_time"),
                "home": match(ev["home_team"]), "away": match(ev["away_team"]),
                "home_api": ev["home_team"], "away_api": ev["away_team"],
                "books": {}, "extras": {}}
        for book in ev.get("bookmakers", []):
            entry = game["books"].setdefault(
                book["key"], {"title": book.get("title", book["key"]), "h2h": {}, "totals": []})
            for market in book.get("markets", []):
                if market["key"] == "h2h":
                    for o in market["outcomes"]:
                        side = ("home" if o["name"] == ev["home_team"]
                                else "away" if o["name"] == ev["away_team"] else "draw")
                        entry["h2h"][side] = o["price"]
                elif market["key"] == "totals":
                    for o in market["outcomes"]:
                        entry["totals"].append({"side": o["name"].lower(),
                                                "line": o.get("point"), "price": o["price"]})
        games.append(game)
    return games


def fetch_odds(cfg, match):
    if not ODDS_API_KEY:
        raise RuntimeError("ODDS_API_KEY secret is not set")
    raw, headers = get(ODDS_URL.format(sport=cfg["odds"], key=ODDS_API_KEY, books=BOOKMAKERS))
    return parse_odds(json.loads(raw), match), to_int(headers.get("x-requests-remaining"))


# ---- Extra markets -----------------------------------------------------------
def kickoff(game):
    try:
        return datetime.fromisoformat(game["kickoff_utc"].replace("Z", "+00:00"))
    except (AttributeError, KeyError, ValueError):
        return None


def eligible_for_extras(games, now):
    """Upcoming games (within the window) that the primary bookmaker has already priced."""
    horizon = now + timedelta(days=EXTRAS_WITHIN_DAYS)
    out = []
    for g in games:
        k = kickoff(g)
        if k and now < k <= horizon and g["books"].get(PRIMARY, {}).get("h2h"):
            out.append(g)
    return out


def clean_outcome(o):
    out = {"name": o.get("name"), "price": o.get("price")}
    for extra in ("point", "description"):
        if o.get(extra) is not None:
            out[extra] = o[extra]
    return out


def fetch_extras(cfg, games, remaining, now=None):
    """Adds game['extras'][PRIMARY][market] for each eligible game.
    A market that errors is skipped for the rest of the run (no paying twice to find out)."""
    now = now or datetime.now(timezone.utc)
    todo = eligible_for_extras(games, now)
    report = {m: {"games_tried": 0, "games_with_data": 0, "error": None} for m in EXTRA_MARKETS}
    stopped = None

    for game in todo:
        for market in EXTRA_MARKETS:
            if stopped:
                break
            if report[market]["error"]:
                continue
            if remaining is not None and remaining <= STOP_EXTRAS_AT_CREDITS:
                stopped = f"stopped early: only {remaining} credits left"
                break
            url = EVENT_ODDS_URL.format(sport=cfg["odds"], event=game["id"],
                                        key=ODDS_API_KEY, book=PRIMARY, market=market)
            try:
                raw, headers = get(url)
                data = json.loads(raw)
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:200]
                report[market]["error"] = f"HTTP {e.code}: {body}"
                if e.code in (401, 429):              # out of credits or rate limited
                    stopped = f"stopped early: {report[market]['error']}"
                continue
            except (urllib.error.URLError, OSError, ValueError) as e:
                report[market]["error"] = str(e)
                continue

            remaining = to_int(headers.get("x-requests-remaining"), remaining)
            report[market]["games_tried"] += 1
            for book in data.get("bookmakers", []):
                if book.get("key") != PRIMARY:
                    continue
                for m in book.get("markets", []):
                    if m.get("key") == market and m.get("outcomes"):
                        game["extras"].setdefault(PRIMARY, {})[market] = {
                            "last_update": m.get("last_update"),
                            "outcomes": [clean_outcome(o) for o in m["outcomes"]],
                        }
                        report[market]["games_with_data"] += 1
        if stopped:
            break

    return {"games_considered": len(todo), "stopped": stopped, "markets": report}, remaining


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

    hist = fetch_history(league, cfg)
    meta["sources"]["history"] = hist
    if not hist["ok"]:
        warn(f"{league} history", "no past seasons available: " + "; ".join(f"{k}: {v}" for k, v in hist["errors"].items()))
    elif hist["missing"]:
        notice(f"{league} history", "could not fetch seasons " + ", ".join(hist["missing"]) + " (the page works without them)")

    known = {m["home"] for m in results} | {m["away"] for m in results}
    matcher = NameMatcher(load_name_map(league), known)
    try:
        games, remaining = fetch_odds(cfg, matcher)
        priced = sum(1 for g in games if g["books"].get(PRIMARY, {}).get("h2h"))
        meta["sources"]["odds"] = {"ok": True, "games": len(games),
                                   f"priced_by_{PRIMARY}": priced}
        if FETCH_EXTRAS:
            try:
                meta["extras"], remaining = fetch_extras(cfg, games, remaining)
            except Exception as e:    # extras are a bonus: never let them break the core odds
                meta["extras"] = {"error": f"{type(e).__name__}: {e}"}
                warn(f"{league} extras", meta["extras"]["error"])
        else:
            meta["extras"] = {"skipped": "FETCH_EXTRAS is off for this run"}
        save(league, "odds.json", games)
        meta["sources"]["odds"]["api_credits_left"] = remaining
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
        print(f"  {src}: {'OK' if info['ok'] else 'FAILED - ' + str(info.get('error', info.get('errors')))}")
    for odds_name, result_name in sorted(matcher.auto.items()):
        print(f"  auto-matched: {odds_name} -> {result_name}")

    extras = meta.get("extras", {})
    if "markets" in extras:
        print(f"  extra markets ({extras['games_considered']} upcoming games):")
        for market, r in extras["markets"].items():
            summary = r["error"] or f"{r['games_with_data']}/{r['games_tried']} games had prices"
            print(f"    {market}: {summary}")
            if r["error"] or (r["games_tried"] and not r["games_with_data"]):
                notice(f"{league} {market}", f"no {PRIMARY} prices: {summary}")
        if extras["stopped"]:
            warn(f"{league} extras", extras["stopped"])
    elif "skipped" in extras:
        print("  extra markets: skipped this run")


def main():
    for league in ENABLED_LEAGUES:
        if league not in LEAGUES:
            warn("Config", f"unknown league '{league}' in ENABLED_LEAGUES")
            continue
        run_league(league)


if __name__ == "__main__":
    main()
