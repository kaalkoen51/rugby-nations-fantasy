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
from datetime import datetime, timezone
from pathlib import Path

from daily_pull import PlayerMatcher, api_get, fix_team_name, load_players

OUT = Path(__file__).parent / "injuries.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--season", type=int, default=2026)
    args = parser.parse_args()

    matcher = PlayerMatcher(load_players())

    # API-Football's injury index is sparse for national teams at the league and
    # team+season level (often empty), so gather from three sources and merge:
    #   1. league+season   2. per team+season   3. per fixture (the authoritative
    # "ruled out of this game" list, which covers tournament injuries best).
    def safe_injuries(params):
        try:
            return api_get("injuries", params).get("response", [])
        except SystemExit:   # unsupported param combo on this plan — skip
            return []

    raw = list(safe_injuries({"league": args.league, "season": args.season}))
    league_n = len(raw)

    teams = api_get("teams", {"league": args.league, "season": args.season}).get(
        "response", [])
    before_team = len(raw)
    for t in teams:
        tid = (t.get("team", {}) or {}).get("id")
        if tid:
            raw += safe_injuries({"team": tid, "season": args.season})
    team_n = len(raw) - before_team

    fixtures = api_get("fixtures", {"league": args.league, "season": args.season}).get(
        "response", [])
    before_fx = len(raw)
    for f in fixtures:
        fid = (f.get("fixture", {}) or {}).get("id")
        if fid:
            raw += safe_injuries({"fixture": fid})
    fixture_n = len(raw) - before_fx

    print(f"Fetched {len(raw)} raw injury report(s) across {len(teams)} teams / "
          f"{len(fixtures)} fixtures (league: {league_n}, team: {team_n}, "
          f"fixture: {fixture_n}).")

    # Flag any injured player the API reports, regardless of the fixture date
    # (API-Football ties an injury to the last fixture missed, which is usually
    # in the past). Freshness is anchored to the build date instead: this feed
    # rebuilds daily, so a recovered player drops out next run, and the app
    # expires entries by `as_of` if the feed ever stops.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    best = {}
    skipped = []
    for it in raw:
        fx_date = (it.get("fixture", {}).get("date") or "")[:10]
        player = it.get("player", {}) or {}
        team = it.get("team", {}).get("name", "")
        ptype = player.get("type") or ""
        print(f"  report: {player.get('name')} ({fix_team_name(team)}) "
              f"type={ptype!r} fixture={fx_date or '—'}")
        entry, how = matcher.match(player.get("name", ""), team, None)
        if not entry:
            skipped.append(f"{player.get('name')} ({fix_team_name(team)}): {how}")
            continue
        status = "out" if ptype.lower().startswith("missing") else "doubtful"
        rec = {
            "player_id": entry["player_id"],
            "status": status,
            "reason": player.get("reason") or "",
            "fixture_date": fx_date,
            "as_of": today,
        }
        prev = best.get(entry["player_id"])
        # Prefer "out" over "doubtful"; within a status, the later fixture.
        if (
            not prev
            or (prev["status"] != "out" and status == "out")
            or (prev["status"] == status and fx_date > (prev["fixture_date"] or ""))
        ):
            best[entry["player_id"]] = rec
    out = sorted(best.values(), key=lambda r: r["player_id"])
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} injury entr{'y' if len(out) == 1 else 'ies'} to {OUT.name}.")
    if skipped:
        print(f"{len(skipped)} report(s) could not be mapped (no badge shown):")
        for s in sorted(set(skipped)):
            print(f"  - {s}")


if __name__ == "__main__":
    main()
