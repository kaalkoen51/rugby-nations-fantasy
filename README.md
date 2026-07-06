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

## Status

A complete, test-passing app. How the pieces stand:

1. **Live stats source: a Google Sheet.** The league keeps a live Google
   Sheet (shape: `docs/rugby_scoring_source_template.xlsx`) and the app pulls
   from it — automatically every ~10 minutes via `sheet-pull.yml`, and on
   demand from **Admin → Pull from sheet**. It's id-keyed (no name-matching),
   needs no API keys, and also feeds the matchday **Starting XV / Bench /
   Not-in-squad** badges. See **Stats & lineups from a Google Sheet** below.
   *(The older Draft Sport API path — `daily_pull.py` / `live_pull.py` — is a
   documented adapter that's still in the tree but disabled; see Stats
   automation.)*

2. **Squads** — `players.json` carries the **real 2026 player pool** (439
   players across the 12 unions, each with their scoring role), built from
   the official "2026 Nations Championship Player List" Google Sheet via
   `python build_players.py --from-mht <export.mht>`. Re-run that (or
   `--placeholder` for a fresh offline pool) if the list changes.

You can also run a full **draft** and score by hand (the admin **Match
stats** form) with no source at all; all logic/tests run offline.

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
| `players.json` | Draft pool: the real 12 squads (439 players, each with a scoring role) |
| `schema.sql` | Supabase schema (idempotent — safe to re-run anytime) |
| `sheet_pull.py` | Pull stats + matchday lineups from the source Google Sheet → `match_stats` / `match_lineups` |
| `docs/rugby_scoring_source_template.xlsx` | The source-sheet template (PlayerStats + Lineups tabs) to copy into Google Sheets |
| `daily_pull.py` | DS-API daily stats pull → rugby fantasy points → `match_stats` upsert (alt. source) |
| `live_pull.py` | In-match live scoring loop (5-min updates while games are on) |
| `build_players.py` | Builds `players.json` (`--from-mht` official sheet, DS-API, or `--placeholder`) |
| `check_picks.py` | Emits SQL to find already-drafted picks whose position no longer matches `players.json` |
| `build_fixtures.py` | Generates `fixtures.json` (confirmed 2026 schedule by default; `--placeholder` synthetic; `--ds-api`) |
| `build_schedule.py` | Regenerates `live-pull.yml` cron triggers from `fixtures.json` |
| `build_photos.py` | Optional player avatars (`photos.json`) |
| `.github/workflows/*` | Sheet pull (stats + lineups) + optional photos |
| `test_logic.js` | Smoke tests for draft order + rugby scoring (`node test_logic.js`) |
| `test_daily_pull.py` | Tests for the id mapping + rugby scoring (`python -m unittest test_daily_pull`) |
| `test_sheet_pull.py` | Tests for the Google-Sheet stats/lineups mapping (`python -m unittest test_sheet_pull`) |

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

The Table tab shows the log (**P** games played, W-D-L, points-for, bonus, log
points) and the current round's matchups with **live scores**; the Home tab
shows your current opponent and who you face next. Cumulative fantasy points
remain the "points for" (PF) column. (Can be turned off in Admin to rank by PF
instead.)

**Odd number of managers?** The round-robin adds a bye each round, so one
manager sits out per round (rotating fairly — everyone byes once per cycle). A
bye scores no log points and isn't a played game; the table shows **P** (played)
and a **"N byes"** note so an uneven `P` is obvious until the byes even out.

### Trade-window limits & waivers (waiver mode on by default)
In **Admin → Trading window**, blank/0 = unlimited (or switch off the
waiver mode for instant real-time
behaviour). You can set:

- **Max trades per manager per window** — caps accepted manager-to-manager trades.
- **Max free-agent claims per window** — caps each manager's pickups.
- **Free agents execute at window close** (default) — pickups are **not
  instant**; they become **waiver claims** that all process when you close the
  window. Each manager queues an **ordered preference list** — list as many
  claims as you like and rank them (reorder with the ▲▼ arrows on the Trades
  tab). At close we walk the **waiver order** (reverse standings, then rolling):
  the top manager gets their **#1** claim; if it's **uncontested** they keep
  priority and continue down their list (up to the per-window cap), and if a
  claim can't run (the player was already taken, or you no longer hold the
  out-player) we **fall through to your next claim** for that slot. **Winning a
  contested claim** (someone else listed the same player) **drops that manager
  to the bottom** of the order. The per-window number caps how many claims each
  manager **executes**, not how many they list. The waiver order is shown
  publicly on the Trades tab.

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

> **The Google Sheet (4b below) is the active source.** The DS-API workflows
> — `daily-pull`, `catchup-pull` and `live-pull` — are **disabled** (their
> schedules are commented out; they remain runnable manually via
> **Actions → Run workflow** if you ever wire up the DS-API). The rest of
> this section describes that DS-API path for reference.

`daily_pull.py` (when enabled) runs every morning via the workflow: fetches
yesterday's completed fixtures, scores them, upserts to `match_stats`. Repo
secrets:

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

### 4b. Stats & lineups from a Google Sheet (recommended)

Instead of (or alongside) the DS-API, keep a live Google Sheet and let the
app pull from it. `sheet_pull.py` reads it and writes both scoring stats and
matchday lineups; because every row carries the squad-list `player_id`, it
needs no name-matching.

1. **Copy the template into Google Sheets.** Import
   `docs/rugby_scoring_source_template.xlsx` (File → Import → Upload). It has
   two tabs you fill — **PlayerStats** (one row per player per match; the
   column names must not change) and **Lineups** (each player's
   Starting/Bench/Not-in-squad status) — plus read-only **Players** (copy
   ids from here), **Fixtures** and **Instructions** tabs.
2. **Publish each tab as CSV.** File → Share → **Publish to web** → choose the
   **PlayerStats** tab → **Comma-separated values (.csv)** → Publish, and copy
   the URL. Repeat for the **Lineups** tab.
3. **Add the repo secrets** (Settings → Secrets and variables → Actions):

   | Secret | Value |
   | --- | --- |
   | `STATS_SHEET_CSV_URL` | published-CSV URL of the **PlayerStats** tab |
   | `LINEUPS_SHEET_CSV_URL` | published-CSV URL of the **Lineups** tab |
   | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` / `FANTASY_LEAGUE_ID` | as above |

The `Sheet stats + lineups pull` workflow then runs every ~10 minutes (and on
demand via **Actions → Run workflow**), upserting `match_stats` (scored live
in the app) and `match_lineups` (the badges). Run it locally with
`python sheet_pull.py --dry-run` to preview without writing. Stats scoring is
unchanged — the same `SCORING` table, keyed by each player's role.

**Matchday badges:** once lineups are pulled, players show a small badge
everywhere their name appears — green **XV** (starting, with shirt number in
the tooltip), gold **B** (bench), or grey **—** (not in the matchday squad),
taken from each player's most recent match in the sheet.

### 5. Create your league & draft
Open the app → **Create a league** (name, managers, seconds/pick — **0 =
unlimited**, no pick clock) → save the invite code + admin token. Everyone
joins; admin hits **Start draft**. Random snake order, 23 rounds; on your turn
you draft any position you still need. The admin can **retune the pick timer
on the fly** from the draft room (Admin — pick timer; `0` = unlimited) — the
new duration applies fresh from the current pick. When a pick times out (or
the admin forces one), the auto-pick is random **from that manager's
shortlist** if they set one, otherwise random from the eligible pool. To leave a league at any time, use
**Exit league** in the top-right header — it returns you to the landing page
where you can join or create another (re-join later with the invite code). After the draft, set your lineup (the XV) via **Home → Pick my team**
any time lineups are **unlocked**. The admin **locks** lineups at kickoff
(snapshotting everyone's lineup) and **unlocks** when the round ends; each
round scores against the snapshot taken at its lock, so later edits never
rewrite an earlier round. The lineup lock is independent of the trading
window, so you can finalise lineups after trades/waivers have executed.

### 6. Admin (Admin tab → unlock with the admin token)
- **Pull from sheet** — paste the published-CSV links for the PlayerStats
  (and optionally Lineups) tabs and pull on demand, straight in the browser:
  the same source as the automatic 10-minute pull, for when you don't want to
  wait for the timer. Links are stored on that device. (If a browser CORS
  block ever stops the fetch, use **Actions → sheet-pull → Run workflow**.)
- **Match stats** — enter/edit per-player rugby stat rows by hand (works
  today, no API needed). Match label format: `Home vs Away (YYYY-MM-DD)`. The
  history list is collapsible.
- **Head-to-Head** — set the scheme + generate fixtures before the draft.
- **Round control** — **Start Round N** at kickoff snapshots every manager's
  lineup, freezes editing, and scoring goes live for the round. **Close Round
  N** finalises scores, reopens editing for the next round (drafted teams
  carry over), resets the **waiver order** to reverse-log order, and clears
  the announced real-life matchday badges. Earlier rounds keep their snapshot.
  Independent of the trading window. The H2H box shows the live round while a
  round is open, and the next round's fixture (blank) between rounds.
- **Trading window** — open between rounds for trades/free-agent claims;
  closing it processes any queued waiver claims. Separate from the lineup lock.

---

## Regenerating data

```bash
pip install -r requirements.txt

python build_players.py --from-mht list.mht   # real squads from the official Google Sheet export
python build_players.py --placeholder          # offline placeholder squads
python build_players.py                        # real squads via DS-API (needs it wired + DRAFT_SPORT_KEY)
python build_fixtures.py                    # confirmed 2026 Nations Championship schedule (default)
python build_fixtures.py --placeholder      # offline synthetic cross-pool schedule
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
