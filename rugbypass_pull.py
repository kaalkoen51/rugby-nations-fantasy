#!/usr/bin/env python3
"""Pull per-player match stats from RugbyPass into match_stats.

RugbyPass carries the deep breakdown stats (metres, tackles, turnovers,
lineouts, scrums, …) the Draft Rugby scoring needs. Its match pages are
rendered from a backend JSON API; this reads that JSON, maps it onto the
app's 27 counting stats, matches each player to a players.json id, and
upserts match_stats (reusing the daily_pull scoring/upsert plumbing).

Run it server-side only (a GitHub Action), never from the browser. Be a
good citizen: low volume, cache, and a real delay between requests.

Two ways to run:
  # live (needs internet — a workflow runner, not the sandbox):
  python rugbypass_pull.py --url "<match stats JSON url>"
  # offline, to iterate on the field mapping from a saved response:
  python rugbypass_pull.py --from-json sample.json --dry-run

Environment (for writes): SUPABASE_URL, SUPABASE_SERVICE_KEY,
FANTASY_LEAGUE_ID (same as the other pulls).

>>> TO FINISH: fill RUGBYPASS_STAT_MAP and the two extract_* functions from
    one real sample (see the devtools steps in the chat). Everything else —
    matching, upsert, CLI, caching, politeness — is done. <<<
"""
import argparse
import json
import os
import sys
import time

import requests

from daily_pull import (
    COUNTING_STATS,
    PlayerMatcher,
    fix_team_name,
    load_players,
    parse_league_ids,
    to_int,
    upsert_match_stats,
)

UA = "rugby-nations-fantasy/1.0 (personal fantasy league; contact: you@example.com)"

# RugbyPass stat field name -> our match_stats column. Fill these in from a
# real player-stats payload (the keys on the left are placeholders).
RUGBYPASS_STAT_MAP = {
    # "Tries": "tries",
    # "MetresMade": "metres",
    # "Carries": "runs",
    # "DefendersBeaten": "defenders_beaten",
    # "CleanBreaks": "clean_breaks",
    # "Passes": "passes",
    # "Offloads": "offloads",
    # "TurnoversConceded": "turnovers_conceded",
    # "TryAssists": "try_assists",
    # "Tackles": "tackles",
    # "MissedTackles": "missed_tackles",
    # "TurnoversWon": "turnovers_won",
    # "Conversions": "conversions",
    # "ConversionsMissed": "conversions_missed",
    # "Penalties": "penalties",
    # "PenaltiesMissed": "penalties_missed",
    # "DropGoals": "drop_goals",
    # "DropGoalsMissed": "drop_goals_missed",
    # "LineoutThrowWon": "lineout_throws_won",
    # "LineoutsWon": "lineouts_taken",
    # "LineoutSteals": "lineout_steals",
    # "PenaltiesConceded": "penalties_conceded",
    # "YellowCards": "yellow_cards",
    # "RedCards": "red_cards",
    # "ScrumsWon": "scrums_won",
    # "ScrumsLost": "scrums_lost",
    # "LineoutsLost": "lineouts_lost",
}


def fetch_json(url: str, cache_dir: str = ".rp_cache") -> dict:
    """GET a RugbyPass JSON endpoint, with a small on-disk cache and a polite
    delay so re-runs don't re-hit the site."""
    os.makedirs(cache_dir, exist_ok=True)
    key = "".join(c if c.isalnum() else "_" for c in url)[-150:]
    path = os.path.join(cache_dir, key + ".json")
    if os.path.exists(path):
        return json.loads(open(path, encoding="utf-8").read())
    resp = requests.get(url, headers={"User-Agent": UA, "Accept": "application/json"},
                        timeout=30)
    resp.raise_for_status()
    data = resp.json()
    open(path, "w", encoding="utf-8").write(json.dumps(data))
    time.sleep(2)                     # be gentle between live requests
    return data


# ---- the two functions to fill from a real sample -------------------------

def extract_match_meta(data: dict) -> dict:
    """Return {home, away, date (YYYY-MM-DD), home_score, away_score}.

    TODO: map from the real payload. Team names must be the squad-list names
    (fix_team_name handles code->name); date is the kickoff date."""
    raise NotImplementedError(
        "Fill extract_match_meta() from a sample RugbyPass match payload.")


def extract_player_rows(data: dict) -> list:
    """Return a list of {name, team, number, minutes, <RugbyPass stat keys>}
    dicts — one per player who featured.

    TODO: map from the real payload (usually a home/away teams block, each
    with a players/lineup array carrying a stats object)."""
    raise NotImplementedError(
        "Fill extract_player_rows() from a sample RugbyPass match payload.")


# ---- generic plumbing (done) ----------------------------------------------

def build_rows(data: dict, matcher: PlayerMatcher, valid_ids=None):
    meta = extract_match_meta(data)
    label = (f"{fix_team_name(meta['home'])} vs {fix_team_name(meta['away'])} "
             f"({meta['date']})")
    rows, skipped = [], []
    for pr in extract_player_rows(data):
        matched, note = matcher.match(pr.get("name", ""), pr.get("team", ""),
                                      pr.get("number"))
        if not matched:
            skipped.append(f"{pr.get('name')} ({pr.get('team')}): {note}")
            continue
        pid = matched["player_id"]
        if valid_ids is not None and pid not in valid_ids:
            skipped.append(f"{pid}: not in players.json")
            continue
        out = {
            "player_id": pid,
            "match_label": label,
            "minutes": to_int(pr.get("minutes")),
            "home_score": to_int(meta.get("home_score")),
            "away_score": to_int(meta.get("away_score")),
        }
        for src, col in RUGBYPASS_STAT_MAP.items():
            out[col] = to_int(pr.get(src))
        for col in COUNTING_STATS:            # default any unmapped stat to 0
            out.setdefault(col, 0)
        if not (out["minutes"] or any(out[c] for c in COUNTING_STATS)):
            continue                          # did not feature
        rows.append(out)
    return rows, skipped, label


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="RugbyPass match-stats JSON URL.")
    src.add_argument("--from-json", metavar="FILE",
                     help="A saved JSON response (offline mapping/testing).")
    ap.add_argument("--league-id", default=os.environ.get("FANTASY_LEAGUE_ID"))
    ap.add_argument("--dry-run", action="store_true",
                    help="Fetch/map but do not write to Supabase.")
    args = ap.parse_args()

    data = (json.loads(open(args.from_json, encoding="utf-8").read())
            if args.from_json else fetch_json(args.url))

    matcher = PlayerMatcher(load_players())
    valid = {p["player_id"] for p in load_players()}
    rows, skipped, label = build_rows(data, matcher, valid)

    for s in skipped:
        print(f"  skip: {s}", file=sys.stderr)
    print(f"{label}: {len(rows)} player row(s), {len(skipped)} skipped.")

    league_ids = parse_league_ids(args.league_id)
    if args.dry_run:
        print("  [dry-run] not writing match_stats.")
        print(json.dumps(rows[:2], indent=2))
        return
    if not league_ids:
        sys.exit("Error: FANTASY_LEAGUE_ID (or --league-id) required to write.")
    upsert_match_stats(rows, league_ids)


if __name__ == "__main__":
    main()
