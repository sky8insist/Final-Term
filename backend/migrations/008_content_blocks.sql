create extension if not exists pgcrypto;

create table if not exists public.content_blocks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid not null references public.materials(id) on delete cascade,
    parent_block_id uuid references public.content_blocks(id) on delete set null,
    block_type text not null,
    content_text text not null,
    structured_data jsonb not null default '{}'::jsonb,
    page_number integer,
    bounding_box jsonb,
    start_time double precision,
    end_time double precision,
    sequence_index integer not null,
    parser_name text not null,
    parser_version text not null,
    confidence double precision,
    source_hash text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint content_blocks_type_check check (block_type in ('paragraph', 'heading', 'table', 'chart', 'image', 'formula', 'audio')),
    constraint content_blocks_sequence_check check (sequence_index >= 0),
    constraint content_blocks_page_check check (page_number is null or page_number > 0),
    constraint content_blocks_time_check check (start_time is null or end_time is null or end_time >= start_time),
    constraint content_blocks_confidence_check check (confidence is null or confidence between 0 and 1),
    constraint content_blocks_source_unique unique (material_id, parser_name, parser_version, source_hash)
);

create index if not exists content_blocks_user_subject_type_idx
    on public.content_blocks (user_id, subject_id, block_type, sequence_index);
create index if not exists content_blocks_material_page_idx
    on public.content_blocks (material_id, page_number, sequence_index);
create index if not exists content_blocks_structured_gin_idx
    on public.content_blocks using gin (structured_data);

alter table public.content_blocks enable row level security;
drop policy if exists "Users manage own content blocks" on public.content_blocks;
create policy "Users manage own content blocks" on public.content_blocks
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
