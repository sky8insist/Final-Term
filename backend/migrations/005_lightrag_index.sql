create extension if not exists pgcrypto;

create table if not exists public.lightrag_material_index (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid not null references public.materials(id) on delete cascade,
    workspace text not null,
    status text not null default 'indexing',
    error_message text,
    indexed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint lightrag_material_index_status_check check (
        status in ('indexing', 'indexed', 'failed')
    ),
    constraint lightrag_material_index_error_message_length check (
        error_message is null or char_length(error_message) <= 2000
    ),
    constraint lightrag_material_index_user_material_unique unique (user_id, material_id)
);

create index if not exists lightrag_material_index_user_subject_idx
    on public.lightrag_material_index (user_id, subject_id, status);

drop trigger if exists lightrag_material_index_set_updated_at on public.lightrag_material_index;

create trigger lightrag_material_index_set_updated_at
before update on public.lightrag_material_index
for each row
execute function public.set_updated_at();

alter table public.lightrag_material_index enable row level security;

drop policy if exists "Users can select own lightrag material index" on public.lightrag_material_index;
drop policy if exists "Users can insert own lightrag material index" on public.lightrag_material_index;
drop policy if exists "Users can update own lightrag material index" on public.lightrag_material_index;
drop policy if exists "Users can delete own lightrag material index" on public.lightrag_material_index;

create policy "Users can select own lightrag material index"
on public.lightrag_material_index
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own lightrag material index"
on public.lightrag_material_index
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own lightrag material index"
on public.lightrag_material_index
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own lightrag material index"
on public.lightrag_material_index
for delete
to authenticated
using (user_id = auth.uid());
