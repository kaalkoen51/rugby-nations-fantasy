# WC Fantasy

World Cup 2026 fantasy league for the friend group: a live snake-draft web
app (`index.html`) backed by Supabase, plus a GitHub Actions job that pulls
match stats from API-Football every morning and scores everyone's players.

**What's here:**

| File | Purpose |
| --- | --- |
| `index.html` | The app: lobby, live snake draft, leaderboard, admin stats entry |
| `players.json` | Draft pool: all 48 squads, 1,248 players, from the official FIFA squad lists |
| `schema.sql` | Supabase schema (idempotent — safe to re-run anytime) |
| `daily_pull.py` | Daily stats pull → fantasy points → `match_stats` upsert |
| `.github/workflows/daily-pull.yml` | Runs the pull daily at 06:00 SAST (04:00 UTC) |
| `build_players.py` | Regenerates `players.json` if FIFA updates squads |
| `build_fixtures.py` | Generates `fixtures.json` (next-fixture info on the Home tab) |
| `backtest.py` | Scores a past World Cup to sanity-check position balance (Actions → "Scoring backtest") |
| `test_logic.js` | Smoke tests for draft order + scoring (`node test_logic.js`) |
| `test_daily_pull.py` | Tests for the API→FIFA player-id mapping (`python -m unittest test_daily_pull`) |

Scoring rules live in one place each: `SCORING` in `daily_pull.py` (mirrored
in `index.html`), and TEAM-pick stage bonuses in `STAGE_BONUS` in
`index.html`. They're kept in sync by hand — change one, change both.

---

## Setup guide (in order)

### 1. Supabase project

1. Go to [supabase.com](https://supabase.com) → New project (free tier is fine).
2. Open **SQL Editor**, paste the full contents of `schema.sql`, run it.
   It's additive and idempotent — if you ran an older version before,
   just run the current one again on top.
3. Note where your keys live (**Project Settings → API**); you'll need them
   in later steps:
   - **Project URL** — e.g. `https://abcdefgh.supabase.co`
   - **anon key** — used by the app in the browser
   - **service_role key** — used only by the daily pull (keep private)

### 2. Push to GitHub & host the app

The repo only exists locally so far. Get it onto GitHub (public repo =
free GitHub Pages + unlimited Actions minutes):

```powershell
winget install GitHub.cli     # then restart the terminal
gh auth login
cd C:\Users\koenj\Documents\wc-fantasy
gh repo create wc-fantasy --public --source . --push
```

Then host the app with GitHub Pages: repo → **Settings → Pages →
Build and deployment → Deploy from a branch** → branch `master`, folder
`/ (root)` → Save. After a minute the app is live at
`https://<your-username>.github.io/wc-fantasy/`.

For local testing instead (or before pushing):

```powershell
cd C:\Users\koenj\Documents\wc-fantasy
python -m http.server
# open http://localhost:8000
```

(Don't open `index.html` directly as a file — it needs HTTP to load
`players.json`.)

### 3. First-run app config

The first time the app opens on any device, it asks for the **Supabase
project URL** and **anon key** from step 1. They're stored in that
browser's localStorage — each manager enters them once on their phone.
Nothing secret: the anon key is meant to be public.

### 4. Daily stats automation

`daily_pull.py` runs every morning at 06:00 SAST via the workflow — it
fetches yesterday's completed fixtures, scores them, and upserts to
`match_stats`, which the leaderboard picks up live. It needs four repo
secrets:

| Secret | Value |
| --- | --- |
| `API_FOOTBALL_KEY` | from [api-football.com](https://www.api-football.com/) dashboard (free tier: 100 req/day, plenty) |
| `SUPABASE_URL` | project URL from step 1 |
| `SUPABASE_SERVICE_KEY` | **service_role** key from step 1 |
| `FANTASY_LEAGUE_ID` | your league's `leagues.id` uuid — exists only after step 5, so come back for this one |

Set them via CLI (each prompts for the value):

```powershell
gh secret set API_FOOTBALL_KEY
gh secret set SUPABASE_URL
gh secret set SUPABASE_SERVICE_KEY
gh secret set FANTASY_LEAGUE_ID
```

or web UI: repo → **Settings → Secrets and variables → Actions → New
repository secret**.

Test it without waiting for 6am: **Actions → Daily stats pull → Run
workflow** (or `gh workflow run daily-pull.yml`). Before the tournament
starts it should report "No completed fixtures found" — that means it's
working.

### 5. Create your league & draft

1. Open the app → **Create a league** (name, number of managers, seconds
   per pick). You get an **invite code** (share with the group) and an
   **admin token** — save the token somewhere safe; it gates stats entry
   and team-stage updates, and is shown only once.
2. Join your own league as a manager from the lobby.
3. **Get `FANTASY_LEAGUE_ID` for step 4:** in Supabase → **Table editor →
   leagues** → copy your league row's `id` uuid, then
   `gh secret set FANTASY_LEAGUE_ID`.
4. Everyone joins with the invite code on their phones; when the lobby is
   full, the admin hits **Start draft**. Random snake order, 14 rounds;
   on your turn you draft **any position you still need** (quota:
   2 GK, 4 DEF, 4 MID, 3 FWD, 1 TEAM), with team/position filters and
   auto-pick if your timer runs out.
5. After the draft (and before each round), set your lineup via
   **Home → Pick my team**: starters are 1 GK, 3 DEF, 3 MID, 2 FWD;
   the other four are subs. Lineups aren't fixed at the draft, but they
   **lock when the admin closes the trading window** — each matchday is
   scored against the lineup/roster that was locked at the time, so
   later changes and trades never rewrite earlier rounds.
6. For next-fixture info on the Home and Trades tabs, run
   `python build_fixtures.py` (needs `API_FOOTBALL_KEY` set) and commit
   the generated `fixtures.json`. Optional but nice. (API-Football names
   a few countries differently from the FIFA squad lists — the scripts
   and app normalize them via a shared `TEAM_NAME_FIX` map.)

**Do a test draft first:** create a throwaway league with 2 managers
(you + a second browser tab in incognito), draft a few rounds, confirm
picks appear live in both tabs. Then create the real league.

### 6. Manual stats & team stages (admin)

In the app: **Admin** tab (leaderboard view) → unlock with the admin token.

- **Pull stats now:** fetch a chosen date's completed matches straight
  from API-Football and write everyone's stats immediately — same rows
  the 06:00 workflow writes, so use either or both. Enter your
  API-Football key once (stored only in that device's browser).
  In-progress games are skipped; pull again after the final whistle.
- **Match stats:** enter/edit/delete per-player rows — fallback or
  supplement to the automation (rows upsert on player + match, so the
  6am pull and manual edits don't duplicate). Use the same match-label
  format the automation writes: `Home vs Away (YYYY-MM-DD)`.
  "Def. actions" = tackles + blocks + interceptions (+1 pt per 2,
  GK excluded).
- **Team stages:** set how far each country has progressed (group → r32 →
  r16 → qf → sf → final → winner). This drives TEAM-pick stage bonuses on
  the leaderboard. The automation never touches this — it's always manual,
  after each knockout round.
- **Trading window & lineup locks:** open/close trading from the same
  admin view. While open, managers can swap free agents, propose trades
  and change lineups (see Trading rules under Reference). **Closing the
  window snapshots and locks every lineup** for the upcoming games —
  open it between rounds once all teams have played, close it before
  the next kickoff. A fallback "re-lock now" button exists in case a
  lock was missed.

### 7. Pre-kickoff checklist (tournament starts tomorrow, June 11)

- [ ] Supabase project created, `schema.sql` run
- [ ] `gh` installed + authenticated; repo pushed (public)
- [ ] GitHub Pages enabled; app loads at the Pages URL on your phone
- [ ] API-Football key obtained
- [ ] Real league created in the app; invite code + admin token saved
- [ ] All 4 repo secrets set (incl. `FANTASY_LEAGUE_ID` from the real league)
- [ ] Workflow run manually once — completes green ("no completed fixtures" is correct pre-tournament)
- [ ] Test draft done in a throwaway league (2 managers, two browser tabs)
- [ ] Invite code + app URL shared with the group
- [ ] Real draft completed before the first match kicks off

First automated stats land the morning of **June 12** (06:00 SAST pull
covering June 11's completed matches).

---

## Reference

### daily_pull.py CLI

```powershell
pip install -r requirements.txt
$env:API_FOOTBALL_KEY = "..."; python daily_pull.py --date 2026-06-15 --dry-run
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--date` | yesterday (UTC) | match date `YYYY-MM-DD` |
| `--league` | `1` (World Cup) | API-Football league id (`10` = friendlies) |
| `--season` | `2026` | season year |
| `--league-id` | `FANTASY_LEAGUE_ID` env var | Supabase `leagues.id` uuid |
| `--dry-run` | off | fetch + calculate, but don't write |
| `--mock` | off | use `mock_data/` sample files, no network |

`--mock` needs sample files that aren't in the repo: add
`mock_data/fixtures.json` (an API-Football `/fixtures` response) and
`mock_data/players_<fixture_id>.json` per fixture.

### Regenerating players.json

If FIFA publishes squad updates (injury replacements):

```powershell
pip install requests pypdf
python build_players.py     # re-downloads the FIFA squad lists PDF
```

Then commit and push the updated `players.json` so the hosted app picks
it up. Player ids are `<fifa code>_<shirt number>` (e.g. `arg_10` =
Messi); TEAM picks use `team:<Country>`.

### Trading rules

Both mechanisms need the trading window open (admin toggle) and respect
position groups — a slot only trades within its position, subs included
(GK/SUB_GK ⇄ GK players, etc.). TEAM picks are never tradable.

- **Free-agent swap:** Trades tab → trading partner "Free Agent Pool"
  (or "swap" on your own roster card) → pick any unpicked player in that
  position, filterable by team. Instant, no approval. The list also shows
  same-position players already on other rosters (badged with their
  owner) — tapping **Trade** on one jumps straight into a pre-filled
  trade proposal with that manager instead.
- **Manager trades:** Trades tab → propose player-for-player pairs (multi-
  player trades supported) to another manager, who can accept (players
  swap immediately), reject, or counter. Counters chain, and pending
  proposals can still be answered after the window closes — only *new*
  proposals require it open.

### Sanity tests

`node test_logic.js` — 49 checks on the snake order, position quotas,
scoring parity with `daily_pull.py` (incl. defensive actions), sub
activation, lineup-lock history replay, stage bonuses, and trade
validity. `python -m unittest test_daily_pull` — 16 tests on the
API-Football → FIFA player-id mapping.
