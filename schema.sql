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

-- Realtime: stream changes to connected clients.
alter publication supabase_realtime add table leagues;
alter publication supabase_realtime add table managers;
alter publication supabase_realtime add table picks;
alter publication supabase_realtime add table match_stats;
alter publication supabase_realtime add table team_stages;

-- RLS with open policies: this is a casual fantasy app for a friend group,
-- not a public product. Tighten these if that ever changes.
alter table leagues enable row level security;
alter table managers enable row level security;
alter table picks enable row level security;
alter table match_stats enable row level security;
alter table team_stages enable row level security;

create policy "open access" on leagues for all using (true) with check (true);
create policy "open access" on managers for all using (true) with check (true);
create policy "open access" on picks for all using (true) with check (true);
create policy "open access" on match_stats for all using (true) with check (true);
create policy "open access" on team_stages for all using (true) with check (true);
