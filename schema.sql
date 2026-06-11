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

alter table managers add column if not exists join_token text;
alter table managers add column if not exists draft_position int;

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
begin
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
                             'lineup_snapshots'] loop
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
                             'lineup_snapshots'] loop
        execute format('alter table %I enable row level security', t);
        execute format('drop policy if exists "open access" on %I', t);
        execute format(
            'create policy "open access" on %I for all using (true) with check (true)', t);
    end loop;
end $$;
