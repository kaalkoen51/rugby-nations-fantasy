# Rugby Nations Fantasy

A live snake-draft fantasy app for the **2026 Nations Championship** — the
same engine as our soccer World Cup draft, ported to rugby. It's a single
web page (`index.html`) backed by Supabase, plus GitHub Actions that pull
match stats and score everyone's players.

The 12 nations, two pools of six:

| Europe | Rest of World |
| --- | --- |
| England, France, Ireland, Scotland, Wales, Italy | New Zealand, South Africa, Australia, Argentina, Japan, Fiji |

Each Europe side plays each Rest-of-World side once (three fixtures in the
July window, three in November), then a finals weekend.

---

## ⚠️ Status: working first iteration — two things to finish

This is a complete, test-passing port. Two items depend on external access
that isn't available yet and are clearly marked in the code:

1. **Live stats source (Draft Sport API).** Stats are meant to come from
   [draftrugby.com](https://draftrugby.com)'s Draft Sport API (DS-API). The
   scoring engine, the player-id matcher and the Supabase upsert are all
   built and tested; the **fetch layer is the documented adapter to repoint
   at the DS-API** (`fetch_fixtures` / `fetch_fixture_players` in
   `daily_pull.py`, and `providerGet` in `index.html`). Field names are
   marked `TODO: confirm vs source`. Some networks block the DS-API host, so
   wire and test it where that host is reachable.

2. **Squads** — `players.json` carries the **real 2026 player pool** (439
   players across the 12 unions, each with their scoring role), built from
   the official "2026 Nations Championship Player List" Google Sheet via
   `python build_players.py --from-mht <export.mht>`. Re-run that (or
   `--placeholder` for a fresh offline pool) if the list changes.

You can run a full **draft** and manual scoring (the admin **Match stats**
form) today; all logic/tests run offline.

**Scoring** is the Draft Rugby system from the league's sheet (see the
Scoring section below). One sheet entry is ambiguous: "Turnovers Conceded =
3 points" is written without a sign; since every other concession is
negative it's scored **−3** — confirm the intended sign. It's a single
value in `SCORING` (`daily_pull.py` + `index.html`).

---

## What's here

| File | Purpose |
| --- | --- |
| `index.html` | The app: lobby, live snake draft, leaderboard, player stats, admin stats entry |
| `players.json` | Draft pool: 12 squads (placeholder until real rosters land) |
| `schema.sql` | Supabase schema (idempotent — safe to re-run anytime) |
| `daily_pull.py` | Daily stats pull → rugby fantasy points → `match_stats` upsert |
| `live_pull.py` | In-match live scoring loop (5-min updates while games are on) |
| `build_players.py` | Builds `players.json` (`--from-mht` official sheet, DS-API, or `--placeholder`) |
| `build_fixtures.py` | Generates `fixtures.json` (DS-API, or `--placeholder` offline) |
| `build_schedule.py` | Regenerates `live-pull.yml` cron triggers from `fixtures.json` |
| `build_injuries.py` / `build_photos.py` | Optional availability badges / avatars |
| `.github/workflows/*` | Daily/catch-up/live pulls + injuries/photos |
| `test_logic.js` | Smoke tests for draft order + rugby scoring (`node test_logic.js`) |
| `test_daily_pull.py` | Tests for the id mapping + rugby scoring (`python -m unittest test_daily_pull`) |

Scoring lives in one place each — `SCORING` in `daily_pull.py`, mirrored by
`SCORING` in `index.html` — kept in sync by hand. The test suites assert the
two stay in step.

---

## Positions & roles

The draft uses **six groups** (the lineup is a starting XV). Scoring uses a
finer **8 roles**, because Draft Rugby scores props differently from
hookers, scrum-halves from fly-halves, etc. Each player carries both a
`role` and its draft `position` group (in `players.json`).

| Group | Roles | Jerseys |
| --- | --- | --- |
| `FR` Front Row | Prop, Hooker | 1, 2, 3 |
| `SR` Second Row | Lock | 4, 5 |
| `BR` Back Row | Loose forward | 6, 7, 8 |
| `HB` Half Backs | Scrum-half, Fly-half | 9, 10 |
| `CE` Centres | Centre | 12, 13 |
| `B3` Back Three | Outside back | 11, 14, 15 |

Plus a `TEAM` pick (a nation, for stage bonuses).

**Draft squad (phase 1):** 22 picks — a starting XV + a 6-man bench + one nation:

- Quota: `FR 4 · SR 3 · BR 4 · HB 3 · CE 3 · B3 4 · TEAM 1`
- Starters (the XV): `FR 3 · SR 2 · BR 3 · HB 2 · CE 2 · B3 3`; the rest are subs.

A sub only scores in a round where its starter didn't feature. Quotas tune
in `PHASE1_QUOTA` / `PHASE1_STARTERS` (`index.html`).

## Scoring

The Draft Rugby system (one `SCORING` table in `daily_pull.py` + `index.html`;
many values are by role — abbreviations: P prop, H hooker, L lock,
Loosie = flanker/No.8, SH scrum-half, FH fly-half):

| Action | Points |
| --- | --- |
| Minutes | 1–59 +1 · 60+ +2 |
| Try | Backs/Centres +10 · FH/SH/Loosies/Hookers +12 · Props/Locks +15 |
| Metres carried | +1 per 10 m (Props +1 per 5 m) |
| Runs | +1 (Props +2) |
| Passes | +1 per 10 (SHs +1 per 5) |
| Defenders beaten +2 · Clean breaks +5 · Offloads +3 | |
| Tackles | +1 (Props +2) · Missed tackles −2 |
| Turnovers won +3 · Turnovers conceded −3¹ | |
| Try assists | +5 (Props/Locks +7) |
| Conversions +2 (−2 missed) · Penalties +3 (−3 missed) · Drop goals +3 (−3 missed) | |
| Lineout throws won +1 · Lineouts taken +2 · Lineout steals +4 · Lineouts lost −2 | |
| Scrums won | Props +1.5 · Hookers/Locks +1 · Loosies +0.5 |
| Scrums lost | Props −3 · Hookers/Locks −2 · Loosies −1 |
| Penalties conceded | −4 (Props −3) |
| Yellow card −10 · Red card −20 | |

¹ The sheet shows "Turnovers Conceded = 3 points" unsigned; scored −3 (a
concession) — confirm with the source.

**TEAM pick** earns cumulative stage bonuses: reaching the **final +15**,
winning the **title +20**. In the final phase, surviving managers predict
the champion for **+5**.

## League formats (optional, admin-set)

Two competition modes layer on top of the draft (Admin tab). Both default
off, so a league runs exactly as before until you turn them on.

### Head-to-Head log table
Enable in **Admin → Head-to-Head**, set the scheme **before the draft**,
then **Generate fixtures** (round-robin; byes for odd manager counts). Each
round you're paired with another manager; your score is your lineup's
fantasy points that round. The standings then **rank by log points** instead
of cumulative total:

- **Win 4 / Draw 2 / Loss 0** (configurable), plus
- **+1 big-win bonus** (win by ≥ the attacking margin, default 25) and
  **+1 small-loss bonus** (lose by ≤ the losing margin, default 7).

The Table tab shows the log (W-D-L, points-for, bonus, log points) and the
current round's matchups with **live scores**; rows still expand to each
manager's lineup history. Cumulative total remains the "points for" column.

### Trade-window limits & waivers
In **Admin → Trading window**, blank/0 = unlimited (the default real-time
behaviour). You can set:

- **Max trades per manager per window** — caps accepted manager-to-manager trades.
- **Max free-agent claims per window** — caps each manager's pickups.
- **Free agents execute at window close** — pickups become **waiver claims**
  that all process when you close the window, in **reverse-standings order**.
  Two managers claiming the same player → the lower-ranked one wins, and
  **winning a contested claim drops that manager to the bottom** of the
  waiver order (rolling priority). Uncontested pickups don't cost priority.

---

## Setup guide

### 1. Supabase
New project → **SQL Editor** → paste `schema.sql` → run. It's idempotent.
Note your **Project URL**, **anon key** (used by the app) and
**service_role key** (used only by the daily pull).

### 2. Host the app
Push to GitHub, then **Settings → Pages → Deploy from a branch** (root). The
app loads at `https://<user>.github.io/<repo>/`. Locally: `python -m
http.server` then open `http://localhost:8000` (it needs HTTP to load
`players.json`).

### 3. First-run config
On first open the app asks for the Supabase **URL** and **anon key** (stored
in that browser's localStorage). The anon key is meant to be public.

### 4. Stats automation
`daily_pull.py` runs every morning via the workflow: fetches yesterday's
completed fixtures, scores them, upserts to `match_stats`. Repo secrets:

| Secret | Value |
| --- | --- |
| `DRAFT_SPORT_KEY` | your Draft Sport API key (once the DS-API is wired) |
| `SUPABASE_URL` | project URL |
| `SUPABASE_SERVICE_KEY` | **service_role** key |
| `FANTASY_LEAGUE_ID` | your league's `leagues.id` uuid (comma-separate several to automate multiple leagues) |

Live in-match scoring (`live_pull.py`) uses the same secrets and is driven
by per-kickoff triggers generated from `fixtures.json` by
`build_schedule.py`. Three layers guarantee nothing is missed: live
triggers, a same-day catch-up sweep, and the morning daily sweep — every
pull is a full idempotent upsert.

### 5. Create your league & draft
Open the app → **Create a league** (name, managers, seconds/pick) → save the
invite code + admin token. Everyone joins; admin hits **Start draft**.
Random snake order, 22 rounds; on your turn you draft any position you still
need. After the draft, set your lineup (the XV) via **Home → Pick my team**;
lineups lock when the admin closes the trading window, so each round scores
against the lineup that was locked at the time.

### 6. Admin (Admin tab → unlock with the admin token)
- **Pull stats now** — fetch a date's completed matches straight from the
  provider (once the DS-API is wired) and write everyone's stats.
- **Match stats** — enter/edit per-player rugby stat rows by hand (works
  today, no API needed). Match label format: `Home vs Away (YYYY-MM-DD)`.
- **Team stages** — set each nation's progress (pool → final → winner) for
  TEAM-pick bonuses; mark teams **out** when eliminated.
- **Trading window & lineup locks** — open between rounds, close before
  kickoff to snapshot lineups.
- **Redrafts & final phase** — as the field narrows, run redrafts with
  smaller, admin-chosen squads; before the final, switch to champion picks.

---

## Regenerating data

```bash
pip install -r requirements.txt

python build_players.py --from-mht list.mht   # real squads from the official Google Sheet export
python build_players.py --placeholder          # offline placeholder squads
python build_players.py                        # real squads via DS-API (needs it wired + DRAFT_SPORT_KEY)
python build_fixtures.py --placeholder     # offline cross-pool schedule
python build_schedule.py                   # refresh live-pull cron triggers from fixtures.json
```

Player ids are `<code>_<number>` (e.g. `eng_10`); TEAM picks use
`team:<Nation>`. Re-run `schema.sql` (always additive) after pulling repo
updates.

## Tests

```bash
node test_logic.js                 # draft order, quotas, rugby scoring, subs, trades, redrafts
python -m unittest test_daily_pull # id mapping, rugby scoring, multi-league fan-out, graceful degradation
```

Both assert the JS and Python `SCORING` tables agree — change one, change
both, and the tests will catch drift.

---

This is a casual app for a friend group: one shared Supabase project with
open RLS policies. Right for people you know, not strangers — for those,
fork the repo for a fully isolated instance.
