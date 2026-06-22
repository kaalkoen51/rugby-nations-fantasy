#!/usr/bin/env python3
"""Live in-match scoring loop for the World Cup fantasy league.

Designed to run from the "Live stats pull" GitHub Actions workflow,
which wakes it every 15 minutes (see .github/workflows/live-pull.yml):

- Nothing live and no kickoff within --max-wait minutes -> exits
  immediately (1-2 API calls, a few seconds of runner time).
- Kickoff within --max-wait (default 90 min) but not yet live ->
  stays alive, polling every --poll seconds; this bridges multi-hour
  gaps in GitHub Actions cron scheduling so nearby games are not missed.
- Kickoff time just passed but API hasn't flagged the fixture live yet ->
  stays alive for --kickoff-grace minutes (default 15) to absorb the
  typical 3-10 min lag before API-Football marks a fixture as "1H".
- Otherwise it polls every --poll seconds: upserts player stats for
  every live fixture, gives each fixture one final pull when it goes
  full-time, and exits once nothing is live or imminent.

Every pull is a full cumulative upsert on (league, player, match), so
restarts, overlaps with the manual "Pull stats now" button, and the
06:00 daily sweep are all safe — the last write simply wins.

Environment variables: same as daily_pull.py (API_FOOTBALL_KEY,
SUPABASE_URL, SUPABASE_SERVICE_KEY, FANTASY_LEAGUE_ID — one league uuid
or a comma-separated allowlist; every listed league gets the same rows,
at no extra API-Football cost).
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

from daily_pull import (
    COMPLETED_STATUSES,
    PlayerMatcher,
    api_get,
    extract_player_rows,
    featured,
    fetch_fixture_players,
    load_players,
    parse_league_ids,
)
from daily_pull import upsert_match_stats

# In-play statuses, including halftime/breaks/shootouts/interruptions.
LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def fetch_live_fixtures(league: int) -> list:
    # live=all then filter: one call either way, and "all" is the parameter
    # form the API documents unambiguously.
    return [f for f in api_get("fixtures", {"live": "all"}).get("response", [])
            if f.get("league", {}).get("id") == league]


def minutes_to_next_kickoff(league: int, season: int):
    resp = api_get(
        "fixtures", {"league": league, "season": season, "next": 1}
    ).get("response", [])
    if not resp:
        return None
    kickoff = datetime.fromisoformat(resp[0]["fixture"]["date"])
    return (kickoff - datetime.now(timezone.utc)).total_seconds() / 60


def fetch_fixture(fixture_id: int) -> dict:
    resp = api_get("fixtures", {"id": fixture_id}).get("response", [])
    return resp[0] if resp else None


def pull_fixture(fixture: dict, matcher: PlayerMatcher, league_ids: list,
                 dry_run: bool) -> None:
    fid = fixture["fixture"]["id"]
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    status = fixture["fixture"]["status"]["short"]
    rows = extract_player_rows(
        fixture, fetch_fixture_players(fid, mock=False), matcher)
    appeared = [r for r in rows if featured(r)]
    matched = [r for r in appeared if r["player_id"]]
    unmatched = len(appeared) - len(matched)
    note = f", {unmatched} unmapped" if unmatched else ""
    log(f"  {home} vs {away} [{status}]: {len(matched)} players{note}")
    if dry_run or not matched:
        return
    upsert_match_stats(matched, league_ids)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", type=int, default=1)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--poll", type=int, default=300,
                        help="seconds between live updates")
    parser.add_argument("--lookahead", type=int, default=15,
                        help="engage if a kickoff is this many minutes away")
    parser.add_argument("--max-minutes", type=int, default=330,
                        help="exit after this long; the next cron resumes")
    parser.add_argument("--max-wait", type=int, default=90,
                        help="stay alive if kickoff is within this many "
                        "minutes (bridges cron scheduling gaps; default: 90)")
    parser.add_argument("--kickoff-grace", type=int, default=15,
                        help="stay alive this many minutes past scheduled "
                        "kickoff while waiting for the API to flag the "
                        "fixture as live (API-Football typically lags "
                        "3-10 min; default: 15)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    league_ids = parse_league_ids(os.environ.get("FANTASY_LEAGUE_ID"))
    if not args.dry_run and not league_ids:
        # Exit green, not red: this watchdog fires every 15 minutes, and a
        # missing league id would otherwise mean ~96 failure mails a day.
        log("WARNING: FANTASY_LEAGUE_ID is not set — nothing to score into. "
            "Create the league, then: gh secret set FANTASY_LEAGUE_ID "
            "(value = your leagues.id uuid from Supabase, or a comma-"
            "separated list of several). Exiting.")
        return

    matcher = PlayerMatcher(load_players())
    deadline = time.monotonic() + args.max_minutes * 60
    watched = set()  # fixture ids we have seen live this run
    grace_until = None  # monotonic timestamp: stay alive past kickoff lag

    while True:
        live = fetch_live_fixtures(args.league)
        live_ids = {f["fixture"]["id"] for f in live}

        for f in live:
            pull_fixture(f, matcher, league_ids, args.dry_run)
        watched |= live_ids

        # One final pull with official full-time data per finished fixture.
        for fid in sorted(watched - live_ids):
            f = fetch_fixture(fid)
            if f and f["fixture"]["status"]["short"] in COMPLETED_STATUSES:
                log("final whistle:")
                pull_fixture(f, matcher, league_ids, args.dry_run)
            watched.discard(fid)

        if not live:
            nxt = minutes_to_next_kickoff(args.league, args.season)
            if nxt is not None and nxt <= args.lookahead:
                # Kickoff is imminent or just passed — arm/extend grace window.
                grace_until = time.monotonic() + args.kickoff_grace * 60
            if grace_until is not None and time.monotonic() < grace_until:
                log("nothing live yet — waiting for API to confirm kickoff.")
            elif nxt is None or nxt > args.max_wait:
                log("nothing live, next kickoff "
                    + (f"in {nxt:.0f} min" if nxt is not None else "unknown")
                    + " — exiting.")
                return
            elif nxt > args.lookahead:
                log(f"next kickoff in {nxt:.0f} min — staying alive.")
            else:
                log(f"kickoff in {nxt:.0f} min — standing by.")

        if time.monotonic() > deadline:
            log("max runtime reached — exiting; the next cron resumes.")
            return
        time.sleep(args.poll)


if __name__ == "__main__":
    main()
