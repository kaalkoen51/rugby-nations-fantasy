#!/usr/bin/env python3
"""Build players.json — the draft pool for the Rugby Nations Championship.

Two modes:

  python build_players.py            # try the Draft Sport API (DS-API)
  python build_players.py --placeholder
                                     # offline: generate a structurally
                                     # correct placeholder pool (no network)

The intended source is draftrugby.com's Draft Sport API. Until the 2026
squads are published (the July international window) and the DS-API host is
reachable, ship the placeholder pool: the 12 unions, correct team codes and
the six position groups, with clearly-marked placeholder player names. Then
re-run without --placeholder to replace the names with the real rosters.

Player ids follow <3-letter code, lowercase>_<squad number>, e.g.
"eng_10" — the id the app keys every roster and all scoring by. Position is
one of the six XV groups: FR, SR, BR, HB, CE, B3 (see POSITION GROUPS in
the README).
"""

import argparse
import email
import html
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PLAYERS_JSON = ROOT / "players.json"

# Repoint at the DS-API base + player-listing endpoint when wiring the live
# source. The DS-API exposes per-competition player listings; the official
# draft-sport client libraries document the exact shape.
API_BASE = "https://api.draftsport.com"

# The 12 Nations Championship unions and their pools. Codes are the lower-
# cased prefix of every player id from that union.
TEAMS = [
    # (name, code, pool)
    ("England",      "ENG", "Europe"),
    ("France",       "FRA", "Europe"),
    ("Ireland",      "IRE", "Europe"),
    ("Scotland",     "SCO", "Europe"),
    ("Wales",        "WAL", "Europe"),
    ("Italy",        "ITA", "Europe"),
    ("New Zealand",  "NZL", "Rest of World"),
    ("South Africa", "RSA", "Rest of World"),
    ("Australia",    "AUS", "Rest of World"),
    ("Argentina",    "ARG", "Rest of World"),
    ("Japan",        "JPN", "Rest of World"),
    ("Fiji",         "FIJ", "Rest of World"),
]

# Scoring roles (eight) — the granularity the Draft Rugby scoring system
# distinguishes (props score differently from hookers, scrum-halves from
# fly-halves, etc.). Each role maps to one of the six draft groups, which
# is what the draft quota / lineup / trades use.
ROLE_GROUP = {
    "PR": "FR",  # prop -> front row
    "HK": "FR",  # hooker -> front row
    "LK": "SR",  # lock -> second row
    "LF": "BR",  # loose forward -> back row
    "SH": "HB",  # scrum-half -> half backs
    "FH": "HB",  # fly-half -> half backs
    "CE": "CE",  # centre
    "OB": "B3",  # outside back -> back three
}
ROLE_LABEL = {
    "PR": "Prop", "HK": "Hooker", "LK": "Lock", "LF": "Loose Forward",
    "SH": "Scrum-half", "FH": "Fly-half", "CE": "Centre", "OB": "Outside Back",
}
# How many of each role a placeholder squad carries. Sums to 33.
ROLE_COMPOSITION = {"PR": 5, "HK": 2, "LK": 4, "LF": 6,
                    "SH": 3, "FH": 2, "CE": 4, "OB": 7}


def build_placeholder() -> list:
    """A full, structurally-correct pool with placeholder names. Names are
    obvious stand-ins ("England Prop 1") to be replaced by the real rosters
    via the DS-API once available."""
    players = []
    for name, code, _pool in TEAMS:
        number = 0
        for role in ROLE_COMPOSITION:
            for i in range(1, ROLE_COMPOSITION[role] + 1):
                number += 1
                players.append(
                    {
                        "player_id": f"{code.lower()}_{number}",
                        "name": f"{name} {ROLE_LABEL[role]} {i}",
                        "position": ROLE_GROUP[role],
                        "role": role,
                        "team": name,
                        "team_code": code,
                    }
                )
    return players


# The official squad list (Google Sheet) labels each player with one of these
# eight positions; map to the granular scoring role.
POS_TO_ROLE = {
    "Prop": "PR", "Hooker": "HK", "Lock": "LK", "Loose Forward": "LF",
    "Scrumhalf": "SH", "Flyhalf": "FH", "Centre": "CE", "Outside Back": "OB",
}
# A few hyphenated-surname players come through with "#N/A" (the sheet's
# position lookup misses them); set their roles by hand.
NA_OVERRIDE = {
    "Jamison Gibson-Park": "SH", "Luke Cowan-Dickie": "HK",
    "Asher Opoku-Fordjour": "PR", "Immanuel Feyi-Waboso": "OB",
    "Gabriel Hamer-Webb": "OB", "Reuben Morgan-Williams": "SH",
    "Louis Rees-Zammit": "OB",
}
NAME_TO_CODE = {name: code for name, code, _pool in TEAMS}


def parse_mht(path: Path):
    """Pull (name, team, position) rows from a Google Sheets .mht export
    (the '2026 Nations Championship Player List' — columns Name/Team/Position
    on Sheet1)."""
    msg = email.message_from_binary_file(open(path, "rb"))
    grid = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            txt = part.get_payload(decode=True).decode("utf-8", "replace")
            if "Loose Forward" in txt or txt.count("<td") > 500:
                grid = txt
                break
    if grid is None:
        sys.exit("Could not find the player grid in the .mht file.")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", grid, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        name, team, pos = cells[1], cells[2], cells[3]
        if name and name != "Name" and team:
            rows.append((name, team, pos))
    return rows


def build_from_mht(path: Path) -> list:
    players, counters, problems = [], {}, []
    for name, team, pos in parse_mht(path):
        role = POS_TO_ROLE.get(pos) or NA_OVERRIDE.get(name)
        code = NAME_TO_CODE.get(team)
        if not code:
            problems.append(f"unknown team {team!r} for {name!r}")
            continue
        if not role:
            problems.append(f"unknown position {pos!r} for {name!r}")
            continue
        n = counters[code] = counters.get(code, 0) + 1
        players.append({
            "player_id": f"{code.lower()}_{n}",
            "name": name,
            "position": ROLE_GROUP[role],
            "role": role,
            "team": team,
            "team_code": code,
        })
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit("Resolve the unmapped rows above (add to NA_OVERRIDE / TEAMS).")
    return players


def fetch_from_ds_api() -> list:
    """Pull the real rosters from the Draft Sport API.

    Maps each DS-API player listing to {player_id, name, position, team,
    team_code}. The DS-API position string is normalised to one of the six
    groups via POSITION_FROM_DS. TODO: confirm the DS-API endpoint path and
    field names against the draft-sport client library, and the host is
    reachable (it is blocked by the network policy in some environments)."""
    import requests  # local import so --placeholder needs no dependency

    key = os.environ.get("DRAFT_SPORT_KEY")
    if not key:
        sys.exit("Error: DRAFT_SPORT_KEY not set (needed for the live DS-API "
                 "pull). Use --placeholder for an offline pool.")
    raise SystemExit(
        "Live DS-API pull is not wired yet: confirm the endpoint/field names "
        "against the draft-sport client library, then implement the mapping "
        "here. Run with --placeholder in the meantime."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--placeholder", action="store_true",
        help="Generate an offline placeholder pool (no network/DS-API).",
    )
    parser.add_argument(
        "--from-mht", metavar="PATH",
        help="Build from the official Google Sheets .mht squad-list export "
        "(columns Name/Team/Position).",
    )
    args = parser.parse_args()

    if args.from_mht:
        players = build_from_mht(Path(args.from_mht))
    elif args.placeholder:
        players = build_placeholder()
    else:
        players = fetch_from_ds_api()

    teams = sorted({p["team_code"] for p in players})
    print(f"{len(players)} players across {len(teams)} teams")
    for code in teams:
        n = sum(1 for p in players if p["team_code"] == code)
        print(f"  {code}: {n} players")

    PLAYERS_JSON.write_text(
        json.dumps(players, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {PLAYERS_JSON}")


if __name__ == "__main__":
    main()
