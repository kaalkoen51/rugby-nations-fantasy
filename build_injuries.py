#!/usr/bin/env python3
"""Build injuries.json — availability hints shown as badges in the app.

Fetches API-Football's injury reports for the tournament, maps each player
to their FIFA squad-list id via the same matcher daily_pull.py uses, and
writes a small JSON the app loads optionally (like fixtures.json):

    [{"player_id": "mex_9", "status": "out", "reason": "Knee Injury",
      "fixture_date": "2026-06-18"}, ...]

"out" = reported missing a fixture; "doubtful" = questionable. The app
auto-expires entries whose fixture_date has passed, so a stale file fails
soft (no badges) and never affects scoring or league data.

Run by .github/workflows/injuries.yml daily; needs API_FOOTBALL_KEY.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daily_pull import PlayerMatcher, api_get, fix_team_name, load_players

OUT = Path(__file__).parent / "injuries.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    matcher = PlayerMatcher(load_players())

    # API-Football's injury coverage for a national-team tournament is sparse at
    # the league level (often empty), so gather reports per team as well and
    # merge. Diagnostic counts are printed so an empty result is explainable.
    raw = list(api_get("injuries", {"league": args.league, "season": args.season})
               .get("response", []))
    league_n = len(raw)
    teams = api_get("teams", {"league": args.league, "season": args.season}).get(
        "response", [])
    for t in teams:
        tid = (t.get("team", {}) or {}).get("id")
        if not tid:
            continue
        raw += api_get("injuries", {"team": tid, "season": args.season}).get(
            "response", [])
    print(f"Fetched {len(raw)} raw injury report(s) "
          f"(league-level: {league_n}, +per-team).")

    # Only reports tied to recent/upcoming fixtures are actionable.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    best = {}
    skipped = []
    n_dated = 0
    for it in raw:
        fx_date = (it.get("fixture", {}).get("date") or "")[:10]
        if not fx_date or fx_date < cutoff:
            continue
        n_dated += 1
        player = it.get("player", {}) or {}
        team = it.get("team", {}).get("name", "")
        entry, how = matcher.match(player.get("name", ""), team, None)
        if not entry:
            skipped.append(f"{player.get('name')} ({fix_team_name(team)}): {how}")
            continue
        status = (
            "out"
            if (player.get("type") or "").lower().startswith("missing")
            else "doubtful"
        )
        rec = {
            "player_id": entry["player_id"],
            "status": status,
            "reason": player.get("reason") or "",
            "fixture_date": fx_date,
        }
        prev = best.get(entry["player_id"])
        # Prefer "out" over "doubtful"; within a status, the later fixture.
        if (
            not prev
            or (prev["status"] != "out" and status == "out")
            or (prev["status"] == status and fx_date > prev["fixture_date"])
        ):
            best[entry["player_id"]] = rec

    print(f"{n_dated} report(s) tied to recent/upcoming fixtures (>= {cutoff}).")
    out = sorted(best.values(), key=lambda r: r["player_id"])
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} injury entr{'y' if len(out) == 1 else 'ies'} to {OUT.name}.")
    if skipped:
        print(f"{len(skipped)} report(s) could not be mapped (no badge shown):")
        for s in sorted(set(skipped)):
            print(f"  - {s}")


if __name__ == "__main__":
    main()
