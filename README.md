# WC Fantasy — daily stats pull

Automation for a World Cup fantasy football league among friends. A GitHub
Actions workflow runs once a day at **06:00 SAST** (04:00 UTC), pulls
completed-match player statistics from [API-Football](https://www.api-football.com/),
calculates fantasy points, and upserts them to a Supabase `match_stats` table.

## How it works

- `daily_pull.py` — fetches yesterday's completed fixtures (status FT/AET/PEN)
  for the configured league, flattens per-player stats, scores them, and
  upserts rows to Supabase via the REST API. Only players who actually
  appeared (minutes > 0) are written. Prints a top-10 scorer summary.
- `schema.sql` — Supabase schema (`leagues`, `managers`, `picks`,
  `match_stats`, `team_stages`) with realtime enabled and open RLS policies
  (casual friend-group app, not a public product).
- `.github/workflows/daily-pull.yml` — the scheduled runner. Also supports
  manual runs via **Actions → Daily stats pull → Run workflow**.
- `players.json` — the draft player pool: all 48 squads (26 players each,
  1,248 total) from the official FIFA squad lists, as a flat array of
  `{player_id, name, position, team, team_code}`. Ids are
  `<lowercase FIFA code>_<shirt number>`, e.g. `arg_10` = Lionel Messi.
- `build_players.py` — regenerates `players.json` from the FIFA squad
  lists PDF (`pip install requests pypdf`, then `python build_players.py`).
  Run it again if FIFA publishes a squad update.

### Scoring

| Stat | Points |
| --- | --- |
| Goal | GK 8 / DEF 6 / MID 5 / FWD 4 |
| Assist | 3 |
| Clean sheet (≥60 min played, team conceded 0) | GK 6 / DEF 4 / MID 1 / FWD 0 |
| Yellow card | −1 |
| Red card | −3 |
| Saves (GK only) | +1 per 2 saves |
| Man of the match (highest rating in fixture, ≥7.5) | 3 |
| Penalty saved | 5 |
| Penalty missed | −2 |

Players who didn't play score 0 and aren't written to the table.

## Setup

### 1. Supabase

1. Create a project at [supabase.com](https://supabase.com).
2. Open **SQL Editor**, paste the contents of `schema.sql`, and run it.
3. Insert a league row and note its id — that's your `FANTASY_LEAGUE_ID`:
   ```sql
   insert into leagues (name) values ('WC 2026 Fantasy') returning id;
   ```
4. From **Project Settings → API**, grab the project URL (`SUPABASE_URL`)
   and the `service_role` key (`SUPABASE_SERVICE_KEY`).

### 2. API-Football

Sign up at [api-football.com](https://www.api-football.com/) and copy your
API key from the dashboard. That's `API_FOOTBALL_KEY`. The free tier
(100 requests/day) is plenty for one daily pull.

### 3. GitHub secrets

The workflow needs four repository secrets:

| Secret | Value |
| --- | --- |
| `API_FOOTBALL_KEY` | your API-Football key |
| `SUPABASE_URL` | e.g. `https://abcdefgh.supabase.co` |
| `SUPABASE_SERVICE_KEY` | the `service_role` key |
| `FANTASY_LEAGUE_ID` | the uuid from the `leagues` insert above |

**Via the web UI:** repo → **Settings → Secrets and variables → Actions →
New repository secret**, add each of the four.

**Via the GitHub CLI** (prompts for the value, so it never lands in shell
history):

```sh
gh secret set API_FOOTBALL_KEY
gh secret set SUPABASE_URL
gh secret set SUPABASE_SERVICE_KEY
gh secret set FANTASY_LEAGUE_ID
```

## Running locally

```sh
pip install -r requirements.txt

# Dry run for a specific date (no Supabase write):
API_FOOTBALL_KEY=... python daily_pull.py --date 2026-06-15 --dry-run

# Full run:
API_FOOTBALL_KEY=... SUPABASE_URL=... SUPABASE_SERVICE_KEY=... \
FANTASY_LEAGUE_ID=... python daily_pull.py
```

CLI options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--date` | yesterday (UTC) | match date `YYYY-MM-DD` |
| `--league` | `1` (World Cup) | API-Football league id (`10` = friendlies) |
| `--season` | `2026` | season year |
| `--league-id` | `FANTASY_LEAGUE_ID` env var | Supabase `leagues.id` uuid |
| `--dry-run` | off | fetch + calculate, but don't write |
| `--mock` | off | use `mock_data/` sample files, no network |

> **Note on `--mock`:** the `mock_data/` sample files are not included in
> this repo, so `--mock` won't work out of the box. To use it, add
> `mock_data/fixtures.json` (an API-Football `/fixtures` response) and
> `mock_data/players_<fixture_id>.json` (a `/fixtures/players` response)
> for each fixture in the sample.
