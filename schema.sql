-- Rugby Nations Championship fantasy league schema
-- Run this in the Supabase SQL editor (Database -> SQL Editor -> New query).

create table if not exists leagues (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    created_at timestamptz default now()
);

create table if not exists managers (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    name text not null,
    created_at timestamptz default now()
);

create table if not exists picks (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    manager_id uuid references managers(id) on delete cascade,
    player_id text not null,
    player_name text,
    position text,
    team text,
    created_at timestamptz default now()
);

create table if not exists match_stats (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    player_id text,
    match_label text,
    appeared bool default true,
    -- rugby counting stats (scored in daily_pull.py / index.html SCORING,
    -- many by the player's role). minutes also scores: 1-59 -> 1, 60+ -> 2.
    tries int default 0,
    metres int default 0,
    runs int default 0,
    defenders_beaten int default 0,
    clean_breaks int default 0,
    passes int default 0,
    offloads int default 0,
    turnovers_conceded int default 0,
    try_assists int default 0,
    tackles int default 0,
    missed_tackles int default 0,
    turnovers_won int default 0,
    conversions int default 0,
    conversions_missed int default 0,
    penalties int default 0,
    penalties_missed int default 0,
    drop_goals int default 0,
    drop_goals_missed int default 0,
    lineout_throws_won int default 0,
    lineouts_taken int default 0,
    lineout_steals int default 0,
    penalties_conceded int default 0,
    red_cards int default 0,
    yellow_cards int default 0,
    scrums_won int default 0,
    scrums_lost int default 0,
    lineouts_lost int default 0,
    created_at timestamptz default now(),
    unique (league_id, player_id, match_label)
);

create table if not exists team_stages (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    team text not null,
    stage text not null,
    created_at timestamptz default now()
);

-- Draft app additions (index.html). Purely additive: nothing daily_pull.py
-- reads or writes changes. Safe to run on an existing database.
-- picks.player_id for the TEAM slot uses the convention "team:<TeamName>",
-- e.g. "team:Ireland"; regular slots use players.json ids like "eng_10".
alter table leagues add column if not exists invite_code text;
alter table leagues add column if not exists trading_open boolean not null default false;
-- Lineup lock, independent of the trading window. Managers edit lineups while
-- unlocked; the admin locks at kickoff (which snapshots everyone's lineup for
-- the round) and unlocks when the round ends. Scoring replays each round
-- against the snapshot taken at its lock, so later edits never rewrite it.
alter table leagues add column if not exists lineups_locked boolean not null default false;
-- Explicit round counter, incremented each time a round is started (lineups
-- locked). Snapshots are tagged with it so scoring groups by round exactly
-- (rather than by snapshot order), and the H2H view knows the current /
-- upcoming round.
alter table leagues add column if not exists round_number int not null default 0;
alter table lineup_snapshots add column if not exists round_number int;
alter table leagues add column if not exists admin_token text;
alter table leagues add column if not exists num_managers int default 8;
alter table leagues add column if not exists pick_duration_seconds int default 60;
alter table leagues add column if not exists current_pick int default 0;
alter table leagues add column if not exists pick_started_at timestamptz;

-- Official match score (points) stored alongside player rows so the banner
-- can display the result regardless of which players are rostered.
-- Nullable so existing rows are unaffected.
alter table match_stats add column if not exists home_score int;
alter table match_stats add column if not exists away_score int;

-- Minutes played, shown in the per-player match log. Nullable; the app
-- shows "played"/"did not play" from `appeared` when it's absent, so rows
-- written before this column (or before a re-pull) still read fine.
alter table match_stats add column if not exists minutes int;

-- Redraft phases: as the tournament field narrows the admin can remove
-- trailing managers (their points freeze) and run redrafts with smaller,
-- admin-chosen squads. Each manager protects one player (picks.kept rides
-- on top of the phase quota); TEAM picks always carry through. In the
-- final phase squads dissolve and surviving managers predict the champion.
alter table leagues add column if not exists phase int not null default 1;
alter table leagues add column if not exists phase_quota jsonb;
alter table leagues add column if not exists phase_starters jsonb;
alter table leagues add column if not exists keeper_window boolean not null default false;
alter table leagues add column if not exists final_phase boolean not null default false;
alter table managers add column if not exists eliminated boolean not null default false;
alter table managers add column if not exists frozen_points int;
-- When a manager was removed, so the history view stops crediting their
-- (now-stale) snapshots for matches played after their elimination.
alter table managers add column if not exists eliminated_at timestamptz;
alter table managers add column if not exists keeper_pick_id uuid;  -- legacy, unused
alter table managers add column if not exists final_pick text;
alter table picks add column if not exists kept boolean not null default false;

-- Keeper rules per redraft, set by the admin when opening keeper picks:
-- keeper_max = how many players each manager may keep (kept players fill
-- squad-quota slots and cost that manager's earliest draft rounds);
-- keeper_caps = optional per-position limits {"GK":1,...}, null = none.
-- keeper_pick_ids = each manager's selections (jsonb array of pick ids).
alter table leagues add column if not exists keeper_max int not null default 1;
alter table leagues add column if not exists keeper_caps jsonb;
alter table managers add column if not exists keeper_pick_ids jsonb;

alter table managers add column if not exists join_token text;
-- Franchise/team name, separate from the manager (person) name. Optional;
-- the app falls back to the manager name for display until one is set.
alter table managers add column if not exists team_name text;
-- Optional team logo, stored inline as a small downscaled data URL (the app
-- crops/compresses to ~96px before saving, so it stays a few KB).
alter table managers add column if not exists team_logo text;
alter table managers add column if not exists draft_position int;
-- Per-manager shortlist of player ids (jsonb array). Synced so it follows
-- the manager across devices; the app only ever renders your own.
alter table managers add column if not exists shortlist jsonb;

-- Per-manager squad planner: { "moves": [ { "out": <pick id>,
-- "choices": [<player id>, ...] } ] } — planned replacements per slot, an
-- ordered first-choice + backups. Synced, only ever rendered for its owner.
alter table managers add column if not exists planner jsonb;

alter table picks add column if not exists pick_number int;
alter table picks add column if not exists is_sub bool default false;
alter table picks add column if not exists slot text;

-- Guard the draft against double-picks from racing clients.
create unique index if not exists picks_league_pick_number_key
    on picks (league_id, pick_number);
create unique index if not exists picks_league_player_key
    on picks (league_id, player_id);

-- One stage row per team per league, so the app can upsert. stage holds
-- one of: pool, final, winner (Nations Championship: pool rounds -> the
-- final-weekend ranking match -> champion).
create unique index if not exists team_stages_league_team_key
    on team_stages (league_id, team);

-- Knocked-out flag (separate from `stage`, which records furthest round
-- reached for the cumulative bonus). The admin marks losers "out" each
-- round; the app then blocks drafting/swapping their players and badges
-- them everywhere. Additive; defaults to still-in.
alter table team_stages add column if not exists eliminated boolean not null default false;

-- Manager-to-manager trades. Each trade_items row pairs one of the
-- proposer's picks with one of the target's picks; the app enforces that
-- both sides of a pair are in the same position group (FR/SR/BR/HB/CE/B3,
-- subs included; TEAM picks are not tradable).
create table if not exists trades (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    proposer_manager_id uuid references managers(id) on delete cascade,
    target_manager_id uuid references managers(id) on delete cascade,
    status text not null default 'proposed'
        check (status in ('proposed','countered','accepted','rejected','cancelled')),
    parent_trade_id uuid references trades(id),
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table if not exists trade_items (
    id uuid primary key default gen_random_uuid(),
    trade_id uuid references trades(id) on delete cascade,
    offered_pick_id uuid references picks(id) on delete cascade,
    requested_pick_id uuid references picks(id) on delete cascade
);

-- Faithful trade history: snapshot the two players' names onto each
-- trade_items row when the proposal is made, so accepted trades read
-- correctly even after the underlying picks are traded again, swapped,
-- or wiped in a redraft. Nullable; older rows fall back to the live pick.
alter table trade_items add column if not exists offered_player_name text;
alter table trade_items add column if not exists requested_player_name text;

-- Stale-player guard: snapshot each pick's player_id when the trade is
-- proposed, so accept_trade can verify the picks still hold those exact
-- players before swapping (a player may have been swapped out / traded
-- away in the meantime). Nullable; trades proposed before this column
-- skip the check and behave as before.
alter table trade_items add column if not exists offered_player_id text;
alter table trade_items add column if not exists requested_player_id text;

-- Roster snapshots: one row per manager per lineup lock. Scoring for a
-- matchday uses the latest snapshot taken on or before that day, so
-- lineup changes and trades never rewrite already-played rounds. Written
-- automatically at draft completion and whenever the admin closes the
-- trading window; roster is the manager's 14 picks as JSON.
create table if not exists lineup_snapshots (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    manager_id uuid references managers(id) on delete cascade,
    effective_from timestamptz not null default now(),
    roster jsonb not null,
    created_at timestamptz default now()
);
create index if not exists lineup_snapshots_lookup_idx
    on lineup_snapshots (league_id, manager_id, effective_from);

-- Transaction log: one row per completed roster move, for the Trades tab's
-- "Transactions" history. Free-agent swaps are written here by the app
-- (doSwap); manager-to-manager trades stay in `trades` and the UI merges both
-- into one chronological list. Display-only -- never affects scoring, so the
-- app degrades gracefully (no log rows) if this migration hasn't been run.
create table if not exists transactions (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    manager_id uuid references managers(id) on delete cascade,
    kind text not null default 'swap',
    out_player_id text,
    out_player_name text,
    in_player_id text,
    in_player_name text,
    created_at timestamptz default now()
);
create index if not exists transactions_league_idx
    on transactions (league_id, created_at);

-- Atomically execute an accepted trade. Swapping player_id between two
-- picks rows as plain updates would trip the unique (league_id, player_id)
-- index mid-swap, so each pair goes through a temp value inside this one
-- transaction.
create or replace function accept_trade(p_trade_id uuid) returns void
language plpgsql as $fn$
declare
    item record;
    a picks%rowtype;
    b picks%rowtype;
    v_open boolean;
begin
    -- Window guard: a pending proposal can only be accepted while the league's
    -- trading window is open. Mirrors the client check so a stale/raced tab
    -- can't slip an acceptance through after the admin closes trading.
    select l.trading_open into v_open
        from trades t join leagues l on l.id = t.league_id
        where t.id = p_trade_id;
    if v_open is distinct from true then
        raise exception 'the trading window is closed';
    end if;
    update trades set status = 'accepted', updated_at = now()
        where id = p_trade_id and status = 'proposed';
    if not found then
        raise exception 'trade is no longer open';
    end if;
    for item in select * from trade_items where trade_id = p_trade_id loop
        select * into a from picks where id = item.offered_pick_id;
        select * into b from picks where id = item.requested_pick_id;
        if a.id is null or b.id is null then
            raise exception 'trade references a missing pick';
        end if;
        -- Stale-player guard: each pick must still hold the player that was
        -- snapshotted at proposal time. If either was traded away or swapped
        -- out since, abort — the raise rolls back this whole transaction,
        -- including the status update above, so the proposal stays open.
        if (item.offered_player_id is not null
                and a.player_id is distinct from item.offered_player_id)
           or (item.requested_player_id is not null
                and b.player_id is distinct from item.requested_player_id) then
            raise exception 'this trade is no longer valid — a player in it was traded away';
        end if;
        update picks set player_id = 'tmp:' || item.id where id = a.id;
        update picks set player_id = a.player_id, player_name = a.player_name,
                         team = a.team where id = b.id;
        update picks set player_id = b.player_id, player_name = b.player_name,
                         team = b.team where id = a.id;
    end loop;
end
$fn$;

-- Trade-window limits & free-agent waivers. window_opened_at marks when the
-- current window opened so per-window counts are "rows since this time".
-- max_*_per_window null/0 = unlimited (the original real-time behaviour).
-- When fa_defer_to_close is true, free-agent pickups queue in fa_claims and
-- run at window close in reverse-standings waiver order. Additive.
alter table leagues add column if not exists window_opened_at timestamptz;
alter table leagues add column if not exists max_trades_per_window int;
alter table leagues add column if not exists max_fa_per_window int;
-- Free agents execute at window close (waiver order) by default in rugby.
alter table leagues add column if not exists fa_defer_to_close boolean not null default true;

-- Optional: point the draft pool at a live "Players" tab (Publish to web ->
-- CSV) instead of the committed players.json. League-wide so every manager's
-- browser loads the same pool from it on refresh. Columns: player_id, name,
-- team, position. Null/blank -> fall back to players.json. Set in Admin.
alter table leagues add column if not exists players_csv_url text;

-- Head-to-Head log table config (set before the draft). H2H is the default
-- standings for rugby: the table ranks by H2H log points, not cumulative
-- total. h2h_score_bonus = an attacking bonus point for scoring at/above this
-- many fantasy points in a round (win or lose); h2h_losing_margin = a losing
-- bonus point for losing by at most this many points.
alter table leagues add column if not exists h2h_enabled boolean not null default true;
alter table leagues add column if not exists h2h_win int not null default 4;
alter table leagues add column if not exists h2h_draw int not null default 2;
alter table leagues add column if not exists h2h_loss int not null default 0;
alter table leagues add column if not exists h2h_score_bonus int not null default 450;
alter table leagues add column if not exists h2h_losing_margin int not null default 50;

-- Rolling waiver priority (lower = picks first). Seeded from reverse
-- standings on the first close; a manager who wins a *contested* claim drops
-- to the bottom. Null until seeded.
alter table managers add column if not exists waiver_order int;

-- Queued free-agent pickups (when fa_defer_to_close). One row per claim;
-- processed at window close. pick_id is the roster slot to fill. Each manager
-- submits an ORDERED preference list (rank ascending) — the window-close
-- resolver works down the list with fallbacks (see resolveFaClaims in
-- index.html). rank is the manager's own ordering; max_fa_per_window caps how
-- many actually execute, not how many are listed.
create table if not exists fa_claims (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    manager_id uuid references managers(id) on delete cascade,
    pick_id uuid references picks(id) on delete cascade,
    rank int not null default 0,
    out_player_id text,
    out_player_name text,
    in_player_id text,
    in_player_name text,
    status text not null default 'pending'
        check (status in ('pending','awarded','failed')),
    created_at timestamptz default now()
);
create index if not exists fa_claims_league_idx on fa_claims (league_id, status);
alter table fa_claims add column if not exists rank int not null default 0;

-- Head-to-Head fixtures: who plays whom each round (round-robin). away_manager_id
-- null = a bye. Generated at draft completion; admin can regenerate.
create table if not exists h2h_fixtures (
    id uuid primary key default gen_random_uuid(),
    league_id uuid references leagues(id) on delete cascade,
    round int not null,
    home_manager_id uuid references managers(id) on delete cascade,
    away_manager_id uuid references managers(id) on delete cascade,
    created_at timestamptz default now()
);
create unique index if not exists h2h_fixtures_round_home_key
    on h2h_fixtures (league_id, round, home_manager_id);

-- Matchday lineups (announced ahead of kickoff). Global, not per league:
-- one row per player per match. status is 'start' | 'bench' | 'out'. The app
-- shows a badge (Starting XV / Bench / Not in squad) from each player's most
-- recent match. Populated by sheet_pull.py from the source Google Sheet.
create table if not exists match_lineups (
    match_label text not null,
    match_date  date,
    player_id   text not null,
    status      text not null check (status in ('start','bench','out')),
    jersey      int,
    updated_at  timestamptz not null default now(),
    primary key (match_label, player_id)
);
create index if not exists match_lineups_player_idx
    on match_lineups (player_id, match_date desc);

-- Realtime: stream changes to connected clients.
-- (wrapped so re-running this file never errors on already-added tables)
do $$
declare t text;
begin
    foreach t in array array['leagues','managers','picks','match_stats',
                             'team_stages','trades','trade_items',
                             'lineup_snapshots','transactions',
                             'fa_claims','h2h_fixtures','match_lineups'] loop
        begin
            execute format('alter publication supabase_realtime add table %I', t);
        exception when duplicate_object then null;
        end;
    end loop;
end $$;

-- RLS with open policies: this is a casual fantasy app for a friend group,
-- not a public product. Tighten these if that ever changes.
-- (drop-then-create keeps re-runs of this file error-free)
do $$
declare t text;
begin
    foreach t in array array['leagues','managers','picks','match_stats',
                             'team_stages','trades','trade_items',
                             'lineup_snapshots','transactions',
                             'fa_claims','h2h_fixtures','match_lineups'] loop
        execute format('alter table %I enable row level security', t);
        execute format('drop policy if exists "open access" on %I', t);
        execute format(
            'create policy "open access" on %I for all using (true) with check (true)', t);
    end loop;
end $$;
