create table if not exists public.clubs (
  id uuid primary key default gen_random_uuid(),
  directory_key text not null unique,
  name text not null,
  city text not null,
  country text not null,
  website text,
  open_days text[] not null default '{}',
  opening_time time,
  closing_time time,
  court_count smallint check (court_count between 1 and 100),
  court_setting text check (court_setting in ('indoor','outdoor','both')),
  has_toilets boolean not null default false,
  has_racket_hire boolean not null default false,
  has_bar_shop boolean not null default false,
  has_seating boolean not null default false,
  has_parking boolean not null default false,
  bus_station text,
  bus_distance_m integer check (bus_distance_m between 0 and 50000),
  train_station text,
  train_distance_m integer check (train_distance_m between 0 and 100000),
  notes text,
  report_count integer not null default 1,
  last_confirmed_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.club_reports (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  club_name text not null check (char_length(club_name) between 1 and 140),
  city text not null check (char_length(city) between 1 and 120),
  country text not null check (char_length(country) between 1 and 100),
  website text check (website is null or char_length(website) <= 500),
  open_days text[] not null default '{}',
  opening_time time,
  closing_time time,
  court_count smallint not null check (court_count between 1 and 100),
  court_setting text not null check (court_setting in ('indoor','outdoor','both')),
  has_toilets boolean not null default false,
  has_racket_hire boolean not null default false,
  has_bar_shop boolean not null default false,
  has_seating boolean not null default false,
  has_parking boolean not null default false,
  bus_station text check (bus_station is null or char_length(bus_station) <= 160),
  bus_distance_m integer check (bus_distance_m between 0 and 50000),
  train_station text check (train_station is null or char_length(train_station) <= 160),
  train_distance_m integer check (train_distance_m between 0 and 100000),
  notes text check (notes is null or char_length(notes) <= 1000),
  created_at timestamptz not null default now()
);

create index if not exists clubs_location_idx on public.clubs(country, city, name);
create index if not exists club_reports_user_idx on public.club_reports(user_id, created_at desc);

alter table public.clubs enable row level security;
alter table public.club_reports enable row level security;

drop policy if exists "authenticated_users_read_clubs" on public.clubs;
create policy "authenticated_users_read_clubs" on public.clubs
  for select to authenticated using (true);

drop policy if exists "users_insert_own_club_reports" on public.club_reports;
create policy "users_insert_own_club_reports" on public.club_reports
  for insert to authenticated with check (auth.uid() = user_id);
drop policy if exists "users_read_own_club_reports" on public.club_reports;
create policy "users_read_own_club_reports" on public.club_reports
  for select to authenticated using (auth.uid() = user_id);

create or replace function public.update_club_from_report() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  club_key text;
begin
  club_key := lower(regexp_replace(trim(new.club_name) || '|' || trim(new.city) || '|' || trim(new.country), '\s+', ' ', 'g'));
  insert into public.clubs (
    directory_key,name,city,country,website,open_days,opening_time,closing_time,court_count,court_setting,
    has_toilets,has_racket_hire,has_bar_shop,has_seating,has_parking,bus_station,bus_distance_m,
    train_station,train_distance_m,notes,report_count,last_confirmed_at
  ) values (
    club_key,trim(new.club_name),trim(new.city),trim(new.country),new.website,new.open_days,new.opening_time,new.closing_time,
    new.court_count,new.court_setting,new.has_toilets,new.has_racket_hire,new.has_bar_shop,new.has_seating,
    new.has_parking,new.bus_station,new.bus_distance_m,new.train_station,new.train_distance_m,new.notes,1,new.created_at
  )
  on conflict (directory_key) do update set
    name=excluded.name,city=excluded.city,country=excluded.country,website=coalesce(excluded.website,clubs.website),
    open_days=case when cardinality(excluded.open_days)>0 then excluded.open_days else clubs.open_days end,
    opening_time=coalesce(excluded.opening_time,clubs.opening_time),closing_time=coalesce(excluded.closing_time,clubs.closing_time),
    court_count=excluded.court_count,court_setting=excluded.court_setting,has_toilets=excluded.has_toilets,
    has_racket_hire=excluded.has_racket_hire,has_bar_shop=excluded.has_bar_shop,has_seating=excluded.has_seating,
    has_parking=excluded.has_parking,bus_station=coalesce(excluded.bus_station,clubs.bus_station),
    bus_distance_m=coalesce(excluded.bus_distance_m,clubs.bus_distance_m),train_station=coalesce(excluded.train_station,clubs.train_station),
    train_distance_m=coalesce(excluded.train_distance_m,clubs.train_distance_m),notes=coalesce(excluded.notes,clubs.notes),
    report_count=clubs.report_count+1,last_confirmed_at=excluded.last_confirmed_at,updated_at=now();
  return new;
end;
$$;

drop trigger if exists club_report_updates_directory on public.club_reports;
create trigger club_report_updates_directory after insert on public.club_reports
for each row execute function public.update_club_from_report();

comment on table public.clubs is 'Community club directory. Signed-in users can read; only the report trigger can change rows.';
comment on table public.club_reports is 'Private user-owned observations used to refresh public club directory facts.';
