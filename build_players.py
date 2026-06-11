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
import unicodedata
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


def fold(s: str) -> str:
    """Accent-insensitive lowercase, for comparing across PDF columns that
    spell the same name with and without diacritics (ALISSON / Álisson)."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


SEAM = "\x01"


def split_seams(s: str) -> str:
    """Mark the column boundaries pypdf glued together with a SEAM char.

    Two seam shapes: lowercase->uppercase ("RamsésBECKER"), and an all-caps
    run followed by a titlecase word ("SANDROAlex" -> before the "A").
    Mc/Mac surname prefixes are the one legitimate in-word case change.
    Seam positions matter: a glue seam is always a column boundary, which
    split_name uses to tell where the PLAYER NAME column ends.
    """
    out = [s[0]] if s else []
    for k in range(1, len(s)):
        a, b = s[k - 1], s[k]
        seam = False
        if a.islower() and b.isupper():
            j = k - 1
            while j > 0 and s[j - 1].isalpha():
                j -= 1
            seam = s[j:k] not in ("Mc", "Mac")
        elif (a.isupper() and b.isupper()
              and k + 1 < len(s) and s[k + 1].islower()):
            seam = True
        if seam:
            out.append(SEAM)
        out.append(s[k])
    return "".join(out)


def tokenize(blob: str):
    """Tokens of the blob plus, per token, whether a glue seam precedes it."""
    tokens, seam_before = [], []
    for part in split_seams(blob).split(" "):
        for j, piece in enumerate(part.split(SEAM)):
            if piece:
                tokens.append(piece)
                seam_before.append(j > 0)
    return tokens, seam_before


def respace(word: str, later: str) -> str:
    """Recover spacing the PDF lost inside an all-caps known-as name.

    The NAME ON SHIRT column often carries the spaced form (ABUHASHEESH
    elsewhere in the row appears as ABU HASHEESH); if a spaced variant of
    `word` occurs later in the row as a whole phrase, adopt its spacing.
    """
    fw, fl = fold(word), fold(later)
    if len(fw) != len(word):  # folding changed length; positions won't map
        return word
    # No word-boundary anchoring: caps-to-caps column gluing is invisible
    # ("...ABUHASHEESHABU HASHEESH"), so the spaced variant may sit mid-
    # "word". Guard against junk splits by requiring 2+ chars per segment.
    pattern = r" ?".join(map(re.escape, fw))
    best = None
    for m in re.finditer(pattern, fl):
        cand = m.group()
        if " " in cand and all(len(seg) >= 2 for seg in cand.split(" ")) and (
            best is None or cand.count(" ") > best.count(" ")
        ):
            best = cand
    if not best:
        return word
    out, i = [], 0
    for ch in best:
        if ch == " ":
            out.append(" ")
        else:
            out.append(word[i])
            i += 1
    return "".join(out)


def split_name(blob: str):
    """Extract (display first name, surname-or-known-as) from a player row.

    The blob is everything between the position code and the date of birth:
    the PLAYER NAME, FIRST NAME(S), LAST NAME(S) and NAME ON SHIRT columns
    run together. PLAYER NAME comes in two conventions:

    - "SURNAME Firstname" (most teams): leading caps run is the surname and
      the display first name follows, usually repeated at the start of
      FIRST NAME(S) ("GUNN AngusAngus Fraser James...").
    - Known-as, all caps (Brazil, Portugal, Arabic-speaking teams): the
      whole column is the display name ("ALEX SANDRO", "NEYMAR JR") and
      FIRST NAME(S) follows directly — recognizable because one of those
      given names re-uses a word of the caps run ("Alex Sandro", "Neymar").
    """
    tokens, seam = tokenize(blob)
    last_parts = []
    i = 0
    while i < len(tokens) and is_caps_token(tokens[i]):
        last_parts.append(tokens[i])
        i += 1
    if not last_parts:
        return None, None
    rest, rseam = tokens[i:], seam[i:]
    if not rest:
        return "", " ".join(last_parts)

    title_run = []
    for tok in rest:
        if is_caps_token(tok):
            break
        title_run.append(tok)

    caps_words = {fold(w) for w in last_parts}
    # Known-as style — the caps run IS the display name — when either the
    # FIRST NAME(S) column was glued straight onto it (the seam proves the
    # PLAYER NAME column held nothing else), or its first given name
    # re-uses a word of the caps run ("WEVERTON Weverton PEREIRA...").
    if title_run and (rseam[0] or fold(title_run[0]) in caps_words):
        later = " ".join(rest)
        return "", " ".join(respace(w, later) for w in last_parts)

    # A glue seam inside the title run likewise marks the exact end of the
    # PLAYER NAME column: what precedes it is the display first name
    # ("YILMAZ Baris Alper|Barış Alper..." -> "Baris Alper").
    for j in range(1, len(title_run)):
        if rseam[j]:
            return " ".join(title_run[:j]), " ".join(last_parts)

    # No seam to go by: the display first name is usually repeated at the
    # start of FIRST NAME(S) ("CACERES Juan Jose Juan Jose...").
    folded = [fold(t) for t in title_run]
    for p in range(1, len(title_run) // 2 + 1):
        if folded[:p] == folded[p : 2 * p]:
            return " ".join(title_run[:p]), " ".join(last_parts)
    return (title_run[0] if title_run else ""), " ".join(last_parts)


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
