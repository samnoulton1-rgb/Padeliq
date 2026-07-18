create extension if not exists pgcrypto;

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  full_name text not null default '',
  playing_side text,
  player_level text,
  primary_goal text,
  age smallint check (age between 13 and 100),
  gender text,
  area text,
  home_club text,
  benchmark_consent boolean not null default false,
  preferred_language text not null default 'en',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.matches (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  match_name text not null,
  played_at date,
  place text,
  court_number text,
  racket text,
  match_score text,
  position_score numeric(5,2) check (position_score between 0 and 100),
  duration_seconds numeric,
  video_filename text,
  video_mime_type text,
  video_size_bytes bigint,
  analysis_status text not null default 'complete',
  analysis_result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists matches_user_played_at_idx on public.matches(user_id, played_at desc);
create index if not exists profiles_benchmark_cohort_idx on public.profiles(age, gender, area, home_club) where benchmark_consent = true;

alter table public.profiles enable row level security;
alter table public.matches enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles for select using (auth.uid() = user_id);
drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own" on public.profiles for insert with check (auth.uid() = user_id);
drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "profiles_delete_own" on public.profiles;
create policy "profiles_delete_own" on public.profiles for delete using (auth.uid() = user_id);

drop policy if exists "matches_select_own" on public.matches;
create policy "matches_select_own" on public.matches for select using (auth.uid() = user_id);
drop policy if exists "matches_insert_own" on public.matches;
create policy "matches_insert_own" on public.matches for insert with check (auth.uid() = user_id);
drop policy if exists "matches_update_own" on public.matches;
create policy "matches_update_own" on public.matches for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
drop policy if exists "matches_delete_own" on public.matches;
create policy "matches_delete_own" on public.matches for delete using (auth.uid() = user_id);

create or replace function public.set_updated_at() returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at before update on public.profiles for each row execute function public.set_updated_at();
drop trigger if exists matches_set_updated_at on public.matches;
create trigger matches_set_updated_at before update on public.matches for each row execute function public.set_updated_at();

create or replace function public.handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (user_id, full_name, playing_side, player_level)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name',''), new.raw_user_meta_data->>'playing_side', new.raw_user_meta_data->>'level')
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function public.handle_new_user();

comment on table public.profiles is 'Private account and benchmark-consent profile data. RLS restricts rows to their owner.';
comment on table public.matches is 'User-owned match metadata and analysis JSON. Raw video is not stored in this table.';
