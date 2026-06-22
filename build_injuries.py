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
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def safe(path, params):
        try:
            return api_get(path, params)            # full payload (response + paging)
        except SystemExit:                          # unsupported combo on this plan
            return {"response": [], "paging": {"current": 1, "total": 1}}

    teams = api_get("teams", {"league": args.league, "season": args.season}).get(
        "response", [])

    # 1) Detailed injury reports (carry a reason/type) from league + per-team.
    raw = list(safe("injuries", {"league": args.league, "season": args.season})
               .get("response", []))
    league_n = len(raw)
    before_team = len(raw)
    for t in teams:
        tid = (t.get("team", {}) or {}).get("id")
        if tid:
            raw += safe("injuries", {"team": tid, "season": args.season}).get("response", [])
    team_n = len(raw) - before_team

    best = {}
    skipped = []
    for it in raw:
        fx_date = (it.get("fixture", {}).get("date") or "")[:10]
        player = it.get("player", {}) or {}
        team = it.get("team", {}).get("name", "")
        ptype = player.get("type") or ""
        entry, how = matcher.match(player.get("name", ""), team, None)
        if not entry:
            skipped.append(f"{player.get('name')} ({fix_team_name(team)}): {how}")
            continue
        status = "out" if ptype.lower().startswith("missing") else "doubtful"
        rec = {"player_id": entry["player_id"], "status": status,
               "reason": player.get("reason") or "Injured",
               "fixture_date": fx_date, "as_of": today}
        prev = best.get(entry["player_id"])
        if (not prev or (prev["status"] != "out" and status == "out")
                or (prev["status"] == status and fx_date > (prev.get("fixture_date") or ""))):
            best[entry["player_id"]] = rec

    # 2) Current injured flag per player via /players (national-team context).
    # This is the broad source: the player object's `injured` boolean reflects
    # current status even when the injury happened at the player's club, which
    # the /injuries endpoints don't surface for a national-team tournament.
    flagged = 0
    scanned = 0
    for t in teams:
        tm = t.get("team", {}) or {}
        tid, tname = tm.get("id"), tm.get("name", "")
        if not tid:
            continue
        page = 1
        while page <= 6:
            data = safe("players", {"team": tid, "season": args.season, "page": page})
            people = data.get("response", [])
            scanned += len(people)
            for e in people:
                p = e.get("player", {}) or {}
                if not p.get("injured"):
                    continue
                entry, how = matcher.match(p.get("name", ""), tname, None)
                if not entry:
                    skipped.append(f"{p.get('name')} ({fix_team_name(tname)}): {how} [injured flag]")
                    continue
                flagged += 1
                print(f"  injured: {p.get('name')} ({fix_team_name(tname)}) -> {entry['player_id']}")
                best.setdefault(entry["player_id"], {
                    "player_id": entry["player_id"], "status": "out",
                    "reason": "Injured", "fixture_date": "", "as_of": today})
            total = (data.get("paging") or {}).get("total", 1)
            if page >= total:
                break
            page += 1

    print(f"Sources: {league_n} league + {team_n} team injury report(s); "
          f"/players scanned {scanned} player-rows across {len(teams)} squads, "
          f"{flagged} flagged injured.")
    out = sorted(best.values(), key=lambda r: r["player_id"])
    OUT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} injury entr{'y' if len(out) == 1 else 'ies'} to {OUT.name}.")
    if skipped:
        print(f"{len(skipped)} report(s) could not be mapped (no badge shown):")
        for s in sorted(set(skipped)):
            print(f"  - {s}")


if __name__ == "__main__":
    main()
