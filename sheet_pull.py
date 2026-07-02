#!/usr/bin/env python3
"""Pull player stats + matchday lineups from the source Google Sheet.

The league keeps a live Google Sheet in the shape of
`docs/rugby_scoring_source_template.xlsx` (tabs `PlayerStats` and `Lineups`).
Each tab is published to the web as CSV (File -> Share -> Publish to web ->
pick the tab -> CSV) and this script reads those CSVs and writes to Supabase:

  PlayerStats -> match_stats   (fanned out across FANTASY_LEAGUE_ID leagues;
                                the app scores these raw counting stats live)
  Lineups     -> match_lineups (global; drives the Starting/Bench/Not-in-squad
                                matchday badges in the app)

This is the id-keyed replacement for the DS-API adapter: because the sheet
already carries each player's `player_id`, no name-matching is needed.

Environment:
  STATS_SHEET_CSV_URL     published CSV url of the PlayerStats tab
  LINEUPS_SHEET_CSV_URL   published CSV url of the Lineups tab (optional)
  SUPABASE_URL            Supabase project url
  SUPABASE_SERVICE_KEY    service_role key
  FANTASY_LEAGUE_ID       one league uuid, or a comma-separated allowlist
"""
import argparse
import csv
import io
import os
import sys

import requests

from daily_pull import (
    COUNTING_STATS,
    fix_team_name,
    load_players,
    parse_league_ids,
    require_env,
    upsert_match_stats,
)

# Sheet status text -> stored status. Generous so the sheet can say
# "Starting"/"Start"/"XV", "Bench"/"Sub", "Not in squad"/"Out"/"N/A".
STATUS_MAP = {
    "starting": "start", "start": "start", "xv": "start", "starter": "start",
    "bench": "bench", "sub": "bench", "substitute": "bench", "replacement": "bench",
    "not in squad": "out", "out": "out", "dropped": "out", "excluded": "out",
    "na": "out", "n/a": "out",
}


def _int(value) -> int:
    """Whole number from a sheet cell; blanks / stray text -> 0."""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def clean_record(raw: dict) -> dict:
    """Strip whitespace from a CSV row's keys and string values."""
    out = {}
    for k, v in raw.items():
        if k is None:
            continue
        out[k.strip()] = v.strip() if isinstance(v, str) else v
    return out


def match_label_of(rec: dict):
    """Build the app's "Home vs Away (YYYY-MM-DD)" label from a row, or None
    when the match columns aren't all filled in."""
    date = (rec.get("date") or "").strip()
    home = (rec.get("home_team") or "").strip()
    away = (rec.get("away_team") or "").strip()
    if not (date and home and away):
        return None
    return f"{fix_team_name(home)} vs {fix_team_name(away)} ({date})"


def stats_rows_from_records(records, valid_ids=None):
    """PlayerStats CSV records -> (upsert rows, skipped notes). Pure: no IO.

    Rows with no player_id are ignored (blank/spacer lines). A row is only
    kept if the player featured (minutes > 0 or any counting stat), matching
    daily_pull's rule so a non-participant never lands a zero row."""
    rows, skipped = [], []
    for raw in records:
        rec = clean_record(raw)
        pid = (rec.get("player_id") or "").strip()
        if not pid:
            continue
        label = match_label_of(rec)
        if not label:
            skipped.append(f"{pid}: missing date/home_team/away_team")
            continue
        if valid_ids is not None and pid not in valid_ids:
            skipped.append(f"{pid}: unknown player_id (not in players.json)")
            continue
        out = {
            "player_id": pid,
            "match_label": label,
            "minutes": _int(rec.get("minutes")),
            "home_score": _int(rec.get("home_score")),
            "away_score": _int(rec.get("away_score")),
        }
        for key in COUNTING_STATS:
            out[key] = _int(rec.get(key))
        if not (out["minutes"] or any(out[key] for key in COUNTING_STATS)):
            continue  # did not feature — nothing to score
        rows.append(out)
    return rows, skipped


def lineup_rows_from_records(records, valid_ids=None):
    """Lineups CSV records -> (match_lineups upsert rows, skipped notes)."""
    rows, skipped = [], []
    for raw in records:
        rec = clean_record(raw)
        pid = (rec.get("player_id") or "").strip()
        status_raw = (rec.get("status") or "").strip().lower()
        if not pid and not status_raw:
            continue  # blank line
        if not pid:
            skipped.append("row with status but no player_id")
            continue
        status = STATUS_MAP.get(status_raw)
        if not status:
            skipped.append(f"{pid}: unrecognised status {rec.get('status')!r}")
            continue
        if valid_ids is not None and pid not in valid_ids:
            skipped.append(f"{pid}: unknown player_id (not in players.json)")
            continue
        label = match_label_of(rec)
        if not label:
            skipped.append(f"{pid}: missing date/home_team/away_team")
            continue
        jersey = _int(rec.get("jersey"))
        rows.append({
            "match_label": label,
            "match_date": (rec.get("date") or "").strip() or None,
            "player_id": pid,
            "status": status,
            "jersey": jersey or None,
        })
    return rows, skipped


def read_csv(url: str) -> list:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    text = resp.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def upsert_lineups(rows: list) -> None:
    """Upsert match_lineups on its (match_label, player_id) key."""
    if not rows:
        print("No lineup rows to write.")
        return
    supabase_url = require_env("SUPABASE_URL", "Supabase project URL")
    service_key = require_env("SUPABASE_SERVICE_KEY", "Supabase service role key")
    resp = requests.post(
        f"{supabase_url.rstrip('/')}/rest/v1/match_lineups",
        params={"on_conflict": "match_label,player_id"},
        headers={
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates",
        },
        json=rows,
        timeout=30,
    )
    if resp.status_code >= 400:
        sys.exit(f"Supabase match_lineups upsert failed "
                 f"({resp.status_code}): {resp.text}")
    print(f"Upserted {len(rows)} lineup row(s) to match_lineups.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats-url", default=os.environ.get("STATS_SHEET_CSV_URL"),
                        help="Published CSV url of the PlayerStats tab.")
    parser.add_argument("--lineups-url", default=os.environ.get("LINEUPS_SHEET_CSV_URL"),
                        help="Published CSV url of the Lineups tab.")
    parser.add_argument("--league-id", default=os.environ.get("FANTASY_LEAGUE_ID"),
                        help="Supabase leagues.id uuid, or a comma-separated allowlist.")
    parser.add_argument("--skip-stats", action="store_true")
    parser.add_argument("--skip-lineups", action="store_true")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and map but do not write to Supabase.")
    args = parser.parse_args()

    valid_ids = {p["player_id"] for p in load_players()}
    league_ids = parse_league_ids(args.league_id)

    did_something = False

    # ---- stats ----
    if not args.skip_stats and args.stats_url:
        did_something = True
        if not args.dry_run and not league_ids:
            sys.exit("Error: FANTASY_LEAGUE_ID (or --league-id) is required to "
                     "write stats.")
        rows, skipped = stats_rows_from_records(read_csv(args.stats_url), valid_ids)
        for note in skipped:
            print(f"  skip (stats): {note}", file=sys.stderr)
        print(f"PlayerStats: {len(rows)} scored row(s), {len(skipped)} skipped.")
        if args.dry_run:
            print("  [dry-run] not writing match_stats.")
        else:
            upsert_match_stats(rows, league_ids)
    elif not args.skip_stats:
        print("STATS_SHEET_CSV_URL not set — skipping the stats pull.")

    # ---- lineups ----
    if not args.skip_lineups and args.lineups_url:
        did_something = True
        rows, skipped = lineup_rows_from_records(read_csv(args.lineups_url), valid_ids)
        for note in skipped:
            print(f"  skip (lineups): {note}", file=sys.stderr)
        print(f"Lineups: {len(rows)} row(s), {len(skipped)} skipped.")
        if args.dry_run:
            print("  [dry-run] not writing match_lineups.")
        else:
            upsert_lineups(rows)
    elif not args.skip_lineups:
        print("LINEUPS_SHEET_CSV_URL not set — skipping the lineups pull.")

    if not did_something:
        # No source URLs configured. Exit cleanly (0) so a scheduled workflow
        # doesn't fail every run before the secrets are set.
        print("Nothing to do: set STATS_SHEET_CSV_URL and/or "
              "LINEUPS_SHEET_CSV_URL (see the module docstring).")


if __name__ == "__main__":
    main()
