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
