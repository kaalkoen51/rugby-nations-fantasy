#!/usr/bin/env python3
"""Daily stats pull for the World Cup fantasy league.

Fetches completed-match player statistics from API-Football, calculates
fantasy points, and upserts them to the Supabase `match_stats` table.

Usage:
    python daily_pull.py                       # yesterday's World Cup fixtures
    python daily_pull.py --date 2026-06-15     # a specific date
    python daily_pull.py --league 10           # friendlies
    python daily_pull.py --dry-run             # fetch + calculate, no writes
    python daily_pull.py --mock --dry-run      # bundled sample data, no network

Environment variables:
    API_FOOTBALL_KEY      required for any non-mock run
    SUPABASE_URL          required for writes (non-dry-run)
    SUPABASE_SERVICE_KEY  required for writes (non-dry-run)
    FANTASY_LEAGUE_ID     Supabase leagues.id uuid, required for writes
                          (can also be passed via --league-id)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

API_BASE = "https://v3.football.api-sports.io"
MOCK_DIR = Path(__file__).parent / "mock_data"

SCORING = {
    "goal": {"GK": 8, "DEF": 6, "MID": 5, "FWD": 4},
    "assist": 3,
    "clean_sheet": {"GK": 6, "DEF": 4, "MID": 1, "FWD": 0},
    "yellow_card": -1,
    "red_card": -3,
    "save_per_2": 1,
    "motm": 3,
    "penalty_saved": 5,
    "penalty_missed": -2,
}

POSITION_MAP = {
    "Goalkeeper": "GK",
    "Defender": "DEF",
    "Midfielder": "MID",
    "Attacker": "FWD",
}

COMPLETED_STATUSES = {"FT", "AET", "PEN"}

MOTM_MIN_RATING = 7.5


def require_env(name: str, why: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Error: environment variable {name} is not set ({why}).")
    return value


def api_get(path: str, params: dict) -> dict:
    key = require_env("API_FOOTBALL_KEY", "needed to call API-Football")
    resp = requests.get(
        f"{API_BASE}/{path}",
        headers={"x-apisports-key": key},
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        sys.exit(f"API-Football error on /{path}: {data['errors']}")
    return data


def load_mock(name: str) -> dict:
    path = MOCK_DIR / f"{name}.json"
    if not path.exists():
        sys.exit(
            f"Error: mock file {path} not found. --mock requires sample data "
            "in mock_data/ (see README)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_fixtures(date: str, league: int, season: int, mock: bool) -> list:
    if mock:
        data = load_mock("fixtures")
    else:
        data = api_get(
            "fixtures", {"date": date, "league": league, "season": season}
        )
    fixtures = data.get("response", [])
    return [
        f
        for f in fixtures
        if f.get("fixture", {}).get("status", {}).get("short")
        in COMPLETED_STATUSES
    ]


def fetch_fixture_players(fixture_id: int, mock: bool) -> list:
    if mock:
        data = load_mock(f"players_{fixture_id}")
    else:
        data = api_get("fixtures/players", {"fixture": fixture_id})
    return data.get("response", [])


def to_int(value) -> int:
    return int(value) if value else 0


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_player_rows(fixture: dict, teams_data: list) -> list:
    """Flatten API-Football fixture-player stats into per-player dicts."""
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    goals = fixture.get("goals", {})
    match_label = f"{home['name']} vs {away['name']} ({fixture['fixture']['date'][:10]})"

    conceded_by_team = {
        home["id"]: to_int(goals.get("away")),
        away["id"]: to_int(goals.get("home")),
    }

    rows = []
    for team_block in teams_data:
        team_id = team_block.get("team", {}).get("id")
        for entry in team_block.get("players", []):
            player = entry.get("player", {})
            stats_list = entry.get("statistics", [])
            stats = stats_list[0] if stats_list else {}
            games = stats.get("games", {}) or {}
            stat_goals = stats.get("goals", {}) or {}
            cards = stats.get("cards", {}) or {}
            penalty = stats.get("penalty", {}) or {}

            minutes = to_int(games.get("minutes"))
            position = POSITION_MAP.get(games.get("position"), "MID")
            team_conceded = conceded_by_team.get(team_id, 0)

            rows.append(
                {
                    "player_id": str(player.get("id")),
                    "player_name": player.get("name", "Unknown"),
                    "position": position,
                    "match_label": match_label,
                    "minutes": minutes,
                    "rating": to_float(games.get("rating")),
                    "goals": to_int(stat_goals.get("total")),
                    "assists": to_int(stat_goals.get("assists")),
                    "saves": to_int(stat_goals.get("saves")),
                    "conceded": team_conceded,
                    "yellow_cards": to_int(cards.get("yellow")),
                    "red_cards": to_int(cards.get("red")),
                    "penalty_saved": to_int(penalty.get("saved")),
                    "penalty_missed": to_int(penalty.get("missed")),
                    "motm": False,  # assigned per fixture below
                }
            )

    assign_motm(rows)
    return rows


def assign_motm(rows: list) -> None:
    """MOTM heuristic: highest-rated player in the fixture, rating >= 7.5."""
    rated = [r for r in rows if r["rating"] is not None and r["minutes"] > 0]
    if not rated:
        return
    best = max(rated, key=lambda r: r["rating"])
    if best["rating"] >= MOTM_MIN_RATING:
        best["motm"] = True


def calculate_points(row: dict) -> int:
    if row["minutes"] == 0:
        return 0

    pos = row["position"]
    points = 0
    points += row["goals"] * SCORING["goal"][pos]
    points += row["assists"] * SCORING["assist"]
    if row["minutes"] >= 60 and row["conceded"] == 0:
        points += SCORING["clean_sheet"][pos]
    points += row["yellow_cards"] * SCORING["yellow_card"]
    points += row["red_cards"] * SCORING["red_card"]
    if pos == "GK":
        points += (row["saves"] // 2) * SCORING["save_per_2"]
    if row["motm"]:
        points += SCORING["motm"]
    points += row["penalty_saved"] * SCORING["penalty_saved"]
    points += row["penalty_missed"] * SCORING["penalty_missed"]
    return points


def upsert_match_stats(rows: list, league_id: str) -> None:
    supabase_url = require_env("SUPABASE_URL", "Supabase project URL")
    service_key = require_env("SUPABASE_SERVICE_KEY", "Supabase service role key")

    payload = [
        {
            "league_id": league_id,
            "player_id": row["player_id"],
            "match_label": row["match_label"],
            "appeared": True,
            "goals": row["goals"],
            "assists": row["assists"],
            "clean_sheet": row["minutes"] >= 60 and row["conceded"] == 0,
            "yellow_cards": row["yellow_cards"],
            "red_cards": row["red_cards"],
            "saves": row["saves"],
            "motm": row["motm"],
            "penalty_saved": row["penalty_saved"],
            "penalty_missed": row["penalty_missed"],
        }
        for row in rows
    ]

    resp = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/match_stats",
        params={"on_conflict": "league_id,player_id,match_label"},
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code >= 400:
        sys.exit(f"Supabase upsert failed ({resp.status_code}): {resp.text}")
    print(f"Upserted {len(payload)} rows to match_stats.")


def print_summary(rows: list) -> None:
    scored = sorted(rows, key=lambda r: r["points"], reverse=True)[:10]
    if not scored:
        print("No player stats to report.")
        return
    print("\nTop 10 scorers:")
    print(f"{'Pts':>4}  {'Pos':<4} {'Player':<28} Match")
    for row in scored:
        print(
            f"{row['points']:>4}  {row['position']:<4} "
            f"{row['player_name']:<28} {row['match_label']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull completed-match player stats and upsert fantasy points."
    )
    parser.add_argument(
        "--date",
        default=(datetime.now(timezone.utc) - timedelta(days=1)).strftime(
            "%Y-%m-%d"
        ),
        help="Match date YYYY-MM-DD (default: yesterday UTC)",
    )
    parser.add_argument(
        "--league",
        type=int,
        default=1,
        help="API-Football league id (default 1 = World Cup; 10 = friendlies)",
    )
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument(
        "--league-id",
        default=os.environ.get("FANTASY_LEAGUE_ID"),
        help="Supabase leagues.id uuid (default: FANTASY_LEAGUE_ID env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and calculate but do not write to Supabase",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use bundled sample data from mock_data/ instead of the network",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.league_id:
        sys.exit(
            "Error: FANTASY_LEAGUE_ID env var (or --league-id) is required "
            "for non-dry-run writes."
        )

    print(
        f"Pulling fixtures for {args.date} "
        f"(league {args.league}, season {args.season})"
        + (" [mock]" if args.mock else "")
        + (" [dry-run]" if args.dry_run else "")
    )

    fixtures = fetch_fixtures(args.date, args.league, args.season, args.mock)
    if not fixtures:
        print("No completed fixtures found for this date. Nothing to do.")
        return
    print(f"Found {len(fixtures)} completed fixture(s).")

    all_rows = []
    for fixture in fixtures:
        fixture_id = fixture["fixture"]["id"]
        teams_data = fetch_fixture_players(fixture_id, args.mock)
        all_rows.extend(extract_player_rows(fixture, teams_data))

    appeared = [r for r in all_rows if r["minutes"] > 0]
    for row in appeared:
        row["points"] = calculate_points(row)

    print(f"{len(appeared)} player(s) appeared across all fixtures.")

    if args.dry_run:
        print("Dry run: skipping Supabase write.")
    else:
        upsert_match_stats(appeared, args.league_id)

    print_summary(appeared)


if __name__ == "__main__":
    main()
