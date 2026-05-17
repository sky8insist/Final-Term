create extension if not exists pgcrypto;

create table if not exists public.material_chunks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid not null references public.materials(id) on delete cascade,
    chunk_index integer not null,
    content text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint material_chunks_chunk_index_non_negative check (chunk_index >= 0),
    constraint material_chunks_content_not_empty check (char_length(content) > 0),
    constraint material_chunks_material_index_unique unique (material_id, chunk_index)
);

create index if not exists material_chunks_user_subject_material_idx
    on public.material_chunks (user_id, subject_id, material_id, chunk_index);

alter table public.material_chunks enable row level security;

drop policy if exists "Users can select own material chunks" on public.material_chunks;
drop policy if exists "Users can insert own material chunks" on public.material_chunks;
drop policy if exists "Users can update own material chunks" on public.material_chunks;
drop policy if exists "Users can delete own material chunks" on public.material_chunks;

create policy "Users can select own material chunks"
on public.material_chunks
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own material chunks"
on public.material_chunks
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own material chunks"
on public.material_chunks
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own material chunks"
on public.material_chunks
for delete
to authenticated
using (user_id = auth.uid());
