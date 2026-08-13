alter table public.material_chunks
    add column if not exists content_block_id uuid references public.content_blocks(id) on delete cascade,
    add column if not exists block_type text,
    add column if not exists page_number integer,
    add column if not exists bounding_box jsonb,
    add column if not exists start_time double precision,
    add column if not exists end_time double precision;

alter table public.material_chunks
    drop constraint if exists material_chunks_block_type_check,
    drop constraint if exists material_chunks_page_check,
    drop constraint if exists material_chunks_time_check;

alter table public.material_chunks
    add constraint material_chunks_block_type_check
        check (block_type is null or block_type in ('paragraph', 'heading', 'table', 'chart', 'image', 'formula', 'audio')),
    add constraint material_chunks_page_check
        check (page_number is null or page_number > 0),
    add constraint material_chunks_time_check
        check (start_time is null or end_time is null or end_time >= start_time);

create index if not exists material_chunks_content_block_idx
    on public.material_chunks (content_block_id, chunk_index);

create index if not exists material_chunks_user_subject_location_idx
    on public.material_chunks (user_id, subject_id, block_type, page_number, start_time);
