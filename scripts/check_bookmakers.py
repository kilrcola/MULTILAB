#!/usr/bin/env python3
"""
One-off bookmaker check for MULTILAB.

Answers: "Which Australian bookmakers actually return over/under goals (and
BTTS, double chance, draw no bet) for this league through The Odds API?"

Costs roughly 5 Odds API credits per run (the run report shows the real number).
Writes data/<league>/bookmaker-check.json and prints a readable summary.
Standard library only.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

SPORT = os.environ.get("SPORT", "soccer_italy_serie_a")
LEAGUE_FOLDER = os.environ.get("LEAGUE_FOLDER", "serie-a")
API_KEY = os.environ.get("ODDS_API_KEY", "")
REGION = "au"
EXTRA_MARKETS = ["btts", "double_chance", "draw_no_bet"]

BASE = "https://api.the-odds-api.com/v4/sports/" + SPORT
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)


def call(url):
    """Returns (json_or_None, headers_lowercased, error_or_None)."""
    req = urllib.request.Request(url, headers={"User-Agent": "multilab/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return json.loads(resp.read()), headers, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        headers = {k.lower(): v for k, v in e.headers.items()}
        return None, headers, f"HTTP {e.code}: {body}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, {}, str(e)


def tally_featured(events):
    """Per bookmaker: in how many games did h2h / totals actually have prices?"""
    books = {}
    for ev in events:
        for book in ev.get("bookmakers", []):
            row = books.setdefault(book["key"], {
                "title": book.get("title", book["key"]),
                "games_with_h2h": 0, "games_with_totals": 0, "totals_lines": set()})
            for market in book.get("markets", []):
                if not market.get("outcomes"):
                    continue
                if market["key"] == "h2h":
                    row["games_with_h2h"] += 1
                elif market["key"] == "totals":
                    row["games_with_totals"] += 1
                    for o in market["outcomes"]:
                        if o.get("point") is not None:
                            row["totals_lines"].add(o["point"])
    for row in books.values():
        row["totals_lines"] = sorted(row["totals_lines"])
    return books


def pick_test_event(events):
    """Soonest game that hasn't started and has at least one bookmaker."""
    now = datetime.now(timezone.utc).isoformat()
    priced = [e for e in events if e.get("bookmakers")]
    upcoming = sorted((e for e in priced if e.get("commence_time", "") > now),
                      key=lambda e: e["commence_time"])
    return (upcoming or priced or [None])[0]


def main():
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "sport": SPORT, "region": REGION, "errors": []}

    if not API_KEY:
        report["errors"].append("ODDS_API_KEY secret is not set")
        finish(report)
        return

    # 1) Standard markets, every AU bookmaker (no bookmaker filter)
    url = (f"{BASE}/odds/?apiKey={API_KEY}&regions={REGION}"
           "&markets=h2h,totals&oddsFormat=decimal")
    events, headers, err = call(url)
    if err:
        report["errors"].append("standard markets: " + err)
        finish(report)
        return
    report["games_in_feed"] = len(events)
    report["standard_markets_by_bookmaker"] = tally_featured(events)
    report["sportsbet_in_feed"] = "sportsbet" in report["standard_markets_by_bookmaker"]

    # 2) Extra markets, tested on a single game to keep the cost low
    ev = pick_test_event(events)
    if ev:
        test = {"game": f"{ev['home_team']} v {ev['away_team']}",
                "kickoff_utc": ev.get("commence_time"), "markets": {}}
        for market in EXTRA_MARKETS:
            url = (f"{BASE}/events/{ev['id']}/odds?apiKey={API_KEY}&regions={REGION}"
                   f"&markets={market}&oddsFormat=decimal")
            data, headers, err = call(url)
            if err:
                test["markets"][market] = {"error": err}
                continue
            have = [b["key"] for b in data.get("bookmakers", [])
                    if any(m["key"] == market and m.get("outcomes") for m in b.get("markets", []))]
            test["markets"][market] = {"bookmakers": have}
        report["extra_markets_test"] = test

    report["credits_remaining"] = headers.get("x-requests-remaining")
    report["credits_used_this_month"] = headers.get("x-requests-used")
    finish(report)


def finish(report):
    out_dir = os.path.join(REPO_ROOT, "data", LEAGUE_FOLDER)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "bookmaker-check.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print(f"Bookmaker check for {report['sport']}")
    for e in report["errors"]:
        print(f"::warning title=Bookmaker check::{e}")
    books = report.get("standard_markets_by_bookmaker", {})
    if books:
        print(f"\nGames in feed: {report['games_in_feed']}")
        print(f"{'bookmaker':16}{'h2h':>6}{'totals':>8}  lines")
        for key, row in sorted(books.items(), key=lambda kv: -kv[1]["games_with_totals"]):
            print(f"{key:16}{row['games_with_h2h']:>6}{row['games_with_totals']:>8}  {row['totals_lines']}")
        print("\nSportsbet in feed:", report["sportsbet_in_feed"])
    test = report.get("extra_markets_test")
    if test:
        print(f"\nExtra markets tested on {test['game']}:")
        for market, res in test["markets"].items():
            print(f"  {market}: {res.get('bookmakers', res.get('error'))}")
    print("\nCredits remaining:", report.get("credits_remaining"))


if __name__ == "__main__":
    main()
