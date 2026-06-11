#!/usr/bin/env python3
"""Build photos.json — player face & team crest ids for the app's avatars.

For every tournament team, pulls API-Football's squad list and maps each
player to their FIFA squad-list id (shirt number + name via the same
matcher daily_pull.py uses). The app turns the ids into image URLs:

    https://media.api-sports.io/football/players/<id>.png
    https://media.api-sports.io/football/teams/<id>.png

Output shape: {"players": {"arg_10": 154, ...}, "teams": {"Argentina": 26}}

photos.json is optional for the app (missing entries fall back to a plain
circle). Run once and commit; re-run if FIFA publishes squad changes.
Needs API_FOOTBALL_KEY; ~49 API calls (1 per team + the team list).
"""

import argparse
import json
from pathlib import Path

from daily_pull import PlayerMatcher, api_get, fix_team_name, load_players

OUT = Path(__file__).parent / "photos.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    matcher = PlayerMatcher(load_players())
    teams = api_get(
        "teams", {"league": args.league, "season": args.season}
    ).get("response", [])
    print(f"{len(teams)} teams in league {args.league}/{args.season}.")

    photos = {"players": {}, "teams": {}}
    unmatched = []
    for t in teams:
        api_team = t.get("team", {}) or {}
        fifa_name = fix_team_name(api_team.get("name", ""))
        photos["teams"][fifa_name] = api_team.get("id")
        squads = api_get("players/squads", {"team": api_team["id"]}).get(
            "response", []
        )
        for sq in squads:
            for p in sq.get("players", []):
                entry, how = matcher.match(
                    p.get("name", ""), api_team.get("name", ""), p.get("number")
                )
                if entry:
                    photos["players"][entry["player_id"]] = p["id"]
                else:
                    unmatched.append(f"{p.get('name')} ({fifa_name}): {how}")

    OUT.write_text(
        json.dumps(photos, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"Wrote {len(photos['players'])} player photos and "
        f"{len(photos['teams'])} team crests to {OUT.name}."
    )
    if unmatched:
        print(f"{len(unmatched)} squad players unmatched (plain circle shown):")
        for s in sorted(set(unmatched)):
            print(f"  - {s}")


if __name__ == "__main__":
    main()
