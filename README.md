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

## Positions

You draft on the **8 scoring positions** (the draft position *is* the
scoring role, so points always match the position you drafted):

`PR` Prop · `HK` Hooker · `LK` Lock · `LF` Loose Forward · `SH` Scrum-half ·
`FH` Fly-half · `CE` Centre · `OB` Outside Back.

**Draft squad:** 23 picks — a starting XV + an 8-man bench:

- Quota: `PR 3 · HK 2 · LK 3 · LF 4 · SH 2 · FH 2 · CE 3 · OB 4`
- Starters (the XV): `PR 2 · HK 1 · LK 2 · LF 3 · SH 1 · FH 1 · CE 2 · OB 3`;
  the rest are subs.

A sub only scores in a round where its starter didn't feature. Quotas tune
in `PHASE1_QUOTA` / `PHASE1_STARTERS` (`index.html`). Admins can set the
snake **draft order** (or randomize) before starting, and managers can
**shortlist players** from the lobby while they wait.

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

## League formats

### Head-to-Head log table (on by default)
The standings **are** a Head-to-Head log. Set the scheme in **Admin →
Head-to-Head** *before the draft*, then **Generate fixtures** (round-robin;
byes for odd manager counts). Each round you're paired with another manager;
your score is your lineup's fantasy points that round, and the table **ranks
by log points**:

- **Win 4 / Draw 2 / Loss 0** (configurable), plus
- **+1 attacking bonus** for scoring at or above the score threshold
  (default **450**, win *or* lose), and
- **+1 losing bonus** for losing within the margin (default **50**).

The Table tab shows the log (W-D-L, points-for, bonus, log points) and the
current round's matchups with **live scores**; the Home tab shows your
current opponent and who you face next. Cumulative fantasy points remain the
"points for" (PF) column. (Can be turned off in Admin to rank by PF instead.)

### Trade-window limits & waivers (waiver mode on by default)
In **Admin → Trading window**, blank/0 = unlimited (or switch off the
waiver mode for instant real-time
behaviour). You can set:

- **Max trades per manager per window** — caps accepted manager-to-manager trades.
- **Max free-agent claims per window** — caps each manager's pickups.
- **Free agents execute at window close** (default) — pickups are **not
  instant**; they become **waiver claims** that all process when you close the
  window, in **reverse-standings order**. Two managers claiming the same player
  → the lower-ranked one wins, and **winning a contested claim drops that
  manager to the bottom** of the waiver order (rolling priority). Uncontested
  pickups don't cost priority. The waiver order is shown publicly on the Trades
  tab.

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
  today, no API needed). Match label format: `Home vs Away (YYYY-MM-DD)`. The
  history list is collapsible.
- **Head-to-Head** — set the scheme + generate fixtures before the draft.
- **Trading window & lineup locks** — open between rounds, close before
  kickoff (which also processes queued waiver claims) to snapshot lineups.

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

Player ids are `<code>_<number>` (e.g. `eng_10`). Re-run `schema.sql`
(always additive) after pulling repo updates.

## Tests

```bash
node test_logic.js                 # draft order, quotas, rugby scoring, subs, trades, H2H, waivers
python -m unittest test_daily_pull # id mapping, rugby scoring, multi-league fan-out, graceful degradation
```

Both assert the JS and Python `SCORING` tables agree — change one, change
both, and the tests will catch drift.

---

This is a casual app for a friend group: one shared Supabase project with
open RLS policies. Right for people you know, not strangers — for those,
fork the repo for a fully isolated instance.
