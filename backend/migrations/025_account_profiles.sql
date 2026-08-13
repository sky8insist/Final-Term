create table if not exists public.profiles (
    id uuid primary key references auth.users(id) on delete cascade,
    username text not null,
    updated_at timestamptz not null default now(),
    constraint profiles_username_format check (username ~ '^[a-z][a-z0-9_]{2,23}$')
);

create unique index if not exists profiles_username_unique_lower
    on public.profiles (lower(username));

alter table public.profiles enable row level security;
drop policy if exists "Users can view own profile" on public.profiles;
create policy "Users can view own profile" on public.profiles
    for select using (auth.uid() = id);
drop policy if exists "Users can update own profile" on public.profiles;
create policy "Users can update own profile" on public.profiles
    for update using (auth.uid() = id) with check (auth.uid() = id);
