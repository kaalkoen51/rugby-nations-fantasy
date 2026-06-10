#!/usr/bin/env python3
"""Build fixtures.json from API-Football so the app can show each player's
(and national team's) next fixture on the Home tab.

    $env:API_FOOTBALL_KEY = "..."; python build_fixtures.py

Re-run and re-commit whenever new fixtures are confirmed (e.g. once
knockout pairings are set). The file is optional — the app shows "no
fixture data" hints without it.
"""

import json
import os
import sys
from pathlib import Path

import requests

API_BASE = "https://v3.football.api-sports.io"


def main() -> None:
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        sys.exit("Error: API_FOOTBALL_KEY env var is required.")
    league = int(os.environ.get("FIXTURES_LEAGUE", "1"))   # 1 = World Cup
    season = int(os.environ.get("FIXTURES_SEASON", "2026"))

    resp = requests.get(
        f"{API_BASE}/fixtures",
        headers={"x-apisports-key": key},
        params={"league": league, "season": season},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        sys.exit(f"API-Football error: {data['errors']}")

    fixtures = [
        {
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
            "kickoff_utc": f["fixture"]["date"],
            "date": f["fixture"]["date"][:10],
            "status": f["fixture"]["status"]["short"],
        }
        for f in data.get("response", [])
    ]
    fixtures.sort(key=lambda f: f["kickoff_utc"])

    out = Path(__file__).parent / "fixtures.json"
    out.write_text(
        json.dumps(fixtures, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(fixtures)} fixtures to {out}")


if __name__ == "__main__":
    main()
