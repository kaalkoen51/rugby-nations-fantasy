-- World Cup fantasy league schema
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
    goals int default 0,
    assists int default 0,
    clean_sheet bool default false,
    yellow_cards int default 0,
    red_cards int default 0,
    saves int default 0,
    motm bool default false,
    penalty_saved int default 0,
    penalty_missed int default 0,
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
-- e.g. "team:Argentina"; regular slots use players.json ids like "arg_10".
alter table leagues add column if not exists invite_code text;
alter table leagues add column if not exists trading_open boolean not null default false;
alter table leagues add column if not exists admin_token text;
alter table leagues add column if not exists num_managers int default 8;
alter table leagues add column if not exists pick_duration_seconds int default 60;
alter table leagues add column if not exists current_pick int default 0;
alter table leagues add column if not exists pick_started_at timestamptz;

-- Defensive contributions: tackles + blocks + interceptions per match,
-- scored as +1 per 2 actions (GK excluded). Additive; older rows stay 0.
alter table match_stats add column if not exists defensive_actions int default 0;

-- Official match score stored alongside player rows so the banner can
-- display the correct result even when own goals are involved (own goals
-- don't appear in any individual player's goals tally). Nullable so
-- existing rows are unaffected; the app falls back to summing player goals
-- for any row written before this column was added.
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
-- one of: group, r32, r16, qf, sf, final, winner.
create unique index if not exists team_stages_league_team_key
    on team_stages (league_id, team);

-- Knocked-out flag (separate from `stage`, which records furthest round
-- reached for the cumulative bonus). The admin marks losers "out" each
-- round; the app then blocks drafting/swapping their players and badges
-- them everywhere. Additive; defaults to still-in.
alter table team_stages add column if not exists eliminated boolean not null default false;

-- Manager-to-manager trades. Each trade_items row pairs one of the
-- proposer's picks with one of the target's picks; the app enforces that
-- both sides of a pair are in the same position group (GK/DEF/MID/FWD,
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

-- Realtime: stream changes to connected clients.
-- (wrapped so re-running this file never errors on already-added tables)
do $$
declare t text;
begin
    foreach t in array array['leagues','managers','picks','match_stats',
                             'team_stages','trades','trade_items',
                             'lineup_snapshots','transactions'] loop
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
                             'lineup_snapshots','transactions'] loop
        execute format('alter table %I enable row level security', t);
        execute format('drop policy if exists "open access" on %I', t);
        execute format(
            'create policy "open access" on %I for all using (true) with check (true)', t);
    end loop;
end $$;
