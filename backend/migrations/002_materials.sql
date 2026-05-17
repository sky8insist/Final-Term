create extension if not exists pgcrypto;

create table if not exists public.materials (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    filename text not null,
    content_type text not null,
    file_size bigint not null,
    status text not null default 'uploaded',
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint materials_filename_length check (char_length(filename) between 1 and 512),
    constraint materials_file_size_non_negative check (file_size >= 0),
    constraint materials_status_check check (
        status in ('uploaded', 'processing', 'ready', 'failed')
    ),
    constraint materials_error_message_length check (
        error_message is null or char_length(error_message) <= 2000
    )
);

create index if not exists materials_user_subject_created_at_idx
    on public.materials (user_id, subject_id, created_at desc);

drop trigger if exists materials_set_updated_at on public.materials;

create trigger materials_set_updated_at
before update on public.materials
for each row
execute function public.set_updated_at();

alter table public.materials enable row level security;

drop policy if exists "Users can select own materials" on public.materials;
drop policy if exists "Users can insert own materials" on public.materials;
drop policy if exists "Users can update own materials" on public.materials;
drop policy if exists "Users can delete own materials" on public.materials;

create policy "Users can select own materials"
on public.materials
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own materials"
on public.materials
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own materials"
on public.materials
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own materials"
on public.materials
for delete
to authenticated
using (user_id = auth.uid());
