#!/usr/bin/env python3
"""Build players.json from the official FIFA squad lists PDF.

Downloads the squad lists for all 48 qualified teams, extracts per-player
name / position / team, and writes a flat players.json for the draft app.

Run manually when squads change (not part of the daily pull):
    pip install requests pypdf
    python build_players.py

Player ids follow <3-letter FIFA code, lowercase>_<shirt number>, e.g.
"arg_10". The PDF lists each squad in shirt-number order (1-26), so the
row index within a team page is the shirt number.
"""

import json
import re
import sys
from pathlib import Path

import requests
from pypdf import PdfReader

PDF_URL = "https://fdp.fifa.org/assetspublic/ce281/pdf/SquadLists-English.pdf"
ROOT = Path(__file__).parent

POSITION_MAP = {"GK": "GK", "DF": "DEF", "MF": "MID", "FW": "FWD"}

TEAM_RE = re.compile(r"^(.{2,40}?) \(([A-Z]{3})\)$")
DOB_RE = re.compile(r"\d{2}/\d{2}/\d{4}")


def fetch_text() -> str:
    pdf_path = ROOT / "SquadLists.pdf"
    if not pdf_path.exists():
        print(f"Downloading {PDF_URL} ...")
        resp = requests.get(PDF_URL, timeout=60)
        resp.raise_for_status()
        pdf_path.write_bytes(resp.content)
    reader = PdfReader(pdf_path)
    text = "\n".join(page.extract_text() for page in reader.pages)
    # pypdf drops the "fi" ligature glyph as a NUL byte (Rafik, Benfica, ...).
    return text.replace("\x00", "fi")


def find_glue(s: str) -> int:
    """Index of the first lowercase->uppercase seam, where two PDF columns
    were extracted without a separating space. -1 if none."""
    for k in range(1, len(s)):
        if s[k - 1].islower() and s[k].isupper():
            return k
    return -1


def is_caps_token(tok: str) -> bool:
    """Surname tokens are all-caps, except a 'Mc' prefix (McTOMINAY)."""
    if tok == tok.upper():
        return True
    return tok.startswith("Mc") and len(tok) > 2 and tok[2:] == tok[2:].upper()


def title_case(name: str) -> str:
    def cap(match: re.Match) -> str:
        word = match.group()
        if re.match(r"^Mc[A-Z]", word):
            return "Mc" + word[2:].capitalize()
        return word.capitalize()

    return re.sub(r"[^\W\d_]+", cap, name)


def display_first(rest: str) -> str:
    """Pick the display first name out of the text following the surname.

    `rest` holds the tail of the PLAYER NAME column (the first name as
    displayed) followed by the FIRST NAME(S), LAST NAME(S) and NAME ON
    SHIRT columns, with column boundaries that are either a space or a
    glue seam. The display name usually reappears verbatim at the start
    of FIRST NAME(S), so try prefixes (shortest first) and keep the one
    that repeats; fall back to seam/token heuristics otherwise.
    """
    seam = find_glue(rest)
    limit = seam if seam != -1 else len(rest)

    ends = [j for j, ch in enumerate(rest[:limit]) if ch == " "] + [limit]
    for e in ends:
        cand = rest[:e]
        if not cand or is_caps_token(cand.split()[-1]):
            break
        after = rest[e:].lstrip()
        if after.startswith(cand) and (
            len(after) == len(cand) or not after[len(cand)].islower()
        ):
            return cand

    if seam != -1:
        tail = rest[seam:]
        if len(tail) >= 2 and tail[1].islower():
            # Title-case after the seam: seam is the boundary between the
            # display name and FIRST NAME(S), e.g. "BambaCheikh Ahmadou..."
            return rest[:seam]
        # Caps after the seam: seam is the FIRST NAME(S) / LAST NAME(S)
        # boundary, e.g. "Nadhir Ahmed NadhirBENBOUALI" -> "Nadhir".

    head = rest.split()[0]
    g = find_glue(head)
    return head[:g] if g != -1 else head


def split_name(blob: str):
    """Split the PLAYER NAME column ("LASTNAME Firstname") out of the blob.

    The blob is everything between the position code and the date of birth,
    i.e. the PLAYER NAME, FIRST NAME(S), LAST NAME(S) and NAME ON SHIRT
    columns run together. The surname is the leading run of all-caps tokens.
    """
    tokens = blob.split()
    last_parts = []
    i = 0
    while i < len(tokens) and is_caps_token(tokens[i]):
        last_parts.append(tokens[i])
        i += 1
    if not last_parts:
        # Mononym glued straight to the next column ("MARQUINHOSMarcos..."):
        # the seam there is caps-followed-by-titlecase.
        tok = tokens[0]
        for k in range(1, len(tok) - 1):
            if tok[k - 1].isupper() and tok[k].isupper() and tok[k + 1].islower():
                return "", tok[:k]
        return None, None
    if i >= len(tokens):
        return "", " ".join(last_parts)
    return display_first(" ".join(tokens[i:])), " ".join(last_parts)


def parse_players(text: str) -> list:
    players = []
    team = code = None
    idx = 0
    problems = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if team is None:
            m = TEAM_RE.match(line)
            if m:
                team, code = m.group(1), m.group(2)
                idx = 0
            continue
        if line.startswith("ROLE COACH"):
            team = code = None
            continue
        if line.startswith("# POS") or line[:2] not in POSITION_MAP:
            continue

        idx += 1
        blob = DOB_RE.split(line[2:])[0].strip()
        first, last = split_name(blob)
        if first is None:
            problems.append(f"{code} #{idx}: could not parse name from {blob!r}")
            first, last = "", blob
        players.append(
            {
                "player_id": f"{code.lower()}_{idx}",
                "name": f"{first} {title_case(last)}".strip(),
                "position": POSITION_MAP[line[:2]],
                "team": team,
                "team_code": code,
            }
        )

    if problems:
        print("\n".join(problems), file=sys.stderr)
    return players


def main() -> None:
    players = parse_players(fetch_text())

    teams = sorted({p["team_code"] for p in players})
    print(f"{len(players)} players across {len(teams)} teams")
    for code in teams:
        n = sum(1 for p in players if p["team_code"] == code)
        if n != 26:
            print(f"  WARNING: {code} has {n} players (expected 26)")

    out = ROOT / "players.json"
    out.write_text(
        json.dumps(players, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
