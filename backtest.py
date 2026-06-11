#!/usr/bin/env python3
"""Sense-check scoring balance across positions on a past World Cup.

Pulls every completed fixture of a season from API-Football, scores all
player appearances with the league's SCORING rules, and reports per-
position averages with and without the defensive-actions rule (+1 per 2
tackles+blocks+interceptions, GK excluded) so the rules can be tuned
until defenders are worth drafting.

    set API_FOOTBALL_KEY=...
    python backtest.py --season 2022

Responses are cached in .api_cache/ so re-runs are free.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import requests

from daily_pull import (
    MOTM_MIN_RATING,
    SCORING,
    POSITION_MAP,
    calculate_points,
    to_float,
    to_int,
)

API_BASE = "https://v3.football.api-sports.io"
CACHE = Path(__file__).parent / ".api_cache"


def cached_get(path: str, params: dict) -> dict:
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("Error: API_FOOTBALL_KEY env var is required.")
    CACHE.mkdir(exist_ok=True)
    name = path.replace("/", "_") + "_" + "_".join(
        f"{k}-{v}" for k, v in sorted(params.items()))
    cache_file = CACHE / f"{name}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    resp = requests.get(f"{API_BASE}/{path}",
                        headers={"x-apisports-key": key},
                        params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        sys.exit(f"API-Football error on /{path}: {data['errors']}")
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2022)
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--stage", choices=("all", "group", "knockout"),
                        default="all", help="filter by tournament stage")
    parser.add_argument("--top", type=int, default=15,
                        help="how many tournament totals to list")
    args = parser.parse_args()

    fixtures = [
        f for f in cached_get("fixtures", {"league": args.league,
                                           "season": args.season})["response"]
        if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")
    ]
    if args.stage != "all":
        in_group = lambda f: f["league"]["round"].startswith("Group")
        fixtures = [f for f in fixtures
                    if in_group(f) == (args.stage == "group")]
    print(f"{len(fixtures)} completed fixtures, season {args.season}"
          f" ({args.stage})")

    rows = []
    for f in fixtures:
        goals = f.get("goals", {})
        conceded_by_team = {
            f["teams"]["home"]["id"]: to_int(goals.get("away")),
            f["teams"]["away"]["id"]: to_int(goals.get("home")),
        }
        teams_data = cached_get(
            "fixtures/players", {"fixture": f["fixture"]["id"]})["response"]
        fixture_rows = []
        for block in teams_data:
            team_id = block.get("team", {}).get("id")
            for entry in block.get("players", []):
                stats = (entry.get("statistics") or [{}])[0]
                games = stats.get("games", {}) or {}
                g = stats.get("goals", {}) or {}
                cards = stats.get("cards", {}) or {}
                pen = stats.get("penalty", {}) or {}
                tackles = stats.get("tackles", {}) or {}
                minutes = to_int(games.get("minutes"))
                if not minutes:
                    continue
                fixture_rows.append({
                    "player_name": entry.get("player", {}).get("name", "?"),
                    "position": POSITION_MAP.get(games.get("position"), "MID"),
                    "minutes": minutes,
                    "rating": to_float(games.get("rating")),
                    "goals": to_int(g.get("total")),
                    "assists": to_int(g.get("assists")),
                    "saves": to_int(g.get("saves")),
                    "conceded": conceded_by_team.get(team_id, 0),
                    "yellow_cards": to_int(cards.get("yellow")),
                    "red_cards": to_int(cards.get("red")),
                    "penalty_saved": to_int(pen.get("saved")),
                    "penalty_missed": to_int(pen.get("missed")),
                    "motm": False,
                    "defensive_actions": (to_int(tackles.get("total"))
                                          + to_int(tackles.get("blocks"))
                                          + to_int(tackles.get("interceptions"))),
                })
        rated = [r for r in fixture_rows if r["rating"] is not None]
        if rated:
            best = max(rated, key=lambda r: r["rating"])
            if best["rating"] >= MOTM_MIN_RATING:
                best["motm"] = True
        rows.extend(fixture_rows)

    for r in rows:
        r["total"] = calculate_points(r)  # includes the defensive-actions rule
        r["dc"] = (r["defensive_actions"] // 2) if r["position"] != "GK" else 0
        r["base"] = r["total"] - r["dc"]

    print(f"{len(rows)} appearances\n")
    print(f"{'Pos':<5}{'apps':>6}{'avg base':>10}{'avg DC':>8}"
          f"{'avg total':>11}{'avg actions':>13}")
    by_pos = defaultdict(list)
    for r in rows:
        by_pos[r["position"]].append(r)
    for pos in ("GK", "DEF", "MID", "FWD"):
        rs = by_pos[pos]
        n = len(rs) or 1
        print(f"{pos:<5}{len(rs):>6}"
              f"{sum(r['base'] for r in rs) / n:>10.2f}"
              f"{sum(r['dc'] for r in rs) / n:>8.2f}"
              f"{sum(r['total'] for r in rs) / n:>11.2f}"
              f"{sum(r['defensive_actions'] for r in rs) / n:>13.2f}")

    totals = defaultdict(lambda: {"pts": 0, "pos": "", "base": 0})
    for r in rows:
        t = totals[r["player_name"]]
        t["pts"] += r["total"]
        t["base"] += r["base"]
        t["pos"] = r["position"]
    print(f"\nTop {args.top} totals, {args.stage} fixtures"
          " (with defensive actions):")
    top = sorted(totals.items(),
                 key=lambda kv: kv[1]["pts"], reverse=True)[:args.top]
    for name, t in top:
        print(f"  {t['pts']:>4} ({t['base']:>3} base)  {t['pos']:<4} {name}")


if __name__ == "__main__":
    main()
