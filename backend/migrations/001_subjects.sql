create extension if not exists pgcrypto;

create table if not exists public.subjects (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    name text not null,
    description text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint subjects_name_length check (char_length(name) between 1 and 120),
    constraint subjects_description_length check (
        description is null or char_length(description) <= 1000
    )
);

create index if not exists subjects_user_created_at_idx
    on public.subjects (user_id, created_at desc);

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists subjects_set_updated_at on public.subjects;

create trigger subjects_set_updated_at
before update on public.subjects
for each row
execute function public.set_updated_at();

alter table public.subjects enable row level security;

drop policy if exists "Users can select own subjects" on public.subjects;
drop policy if exists "Users can insert own subjects" on public.subjects;
drop policy if exists "Users can update own subjects" on public.subjects;
drop policy if exists "Users can delete own subjects" on public.subjects;

create policy "Users can select own subjects"
on public.subjects
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own subjects"
on public.subjects
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own subjects"
on public.subjects
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own subjects"
on public.subjects
for delete
to authenticated
using (user_id = auth.uid());
