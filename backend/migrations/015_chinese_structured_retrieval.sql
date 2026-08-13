create extension if not exists pg_trgm;

create index if not exists content_blocks_text_trgm_idx
    on public.content_blocks using gin (content_text gin_trgm_ops);

create index if not exists content_blocks_structured_text_trgm_idx
    on public.content_blocks using gin ((structured_data::text) gin_trgm_ops);

create or replace function public.search_content_blocks(
    query_text text,
    target_user_id uuid,
    target_subject_id uuid,
    target_material_ids uuid[] default null,
    target_block_types text[] default null,
    min_confidence double precision default null,
    result_limit integer default 10
)
returns table (
    id uuid, material_id uuid, filename text, block_type text, content_text text,
    page_number integer, start_time double precision, end_time double precision,
    confidence double precision, rank real
)
language sql stable security invoker as $$
    with normalized as (
        select nullif(trim(query_text), '') as query
    )
    select cb.id, cb.material_id, m.filename, cb.block_type, cb.content_text,
           cb.page_number, cb.start_time, cb.end_time, cb.confidence,
           greatest(
               ts_rank_cd(cb.search_vector, websearch_to_tsquery('simple', normalized.query)),
               similarity(cb.content_text, normalized.query),
               similarity(cb.structured_data::text, normalized.query)
           )::real as rank
    from public.content_blocks cb
    join public.materials m on m.id = cb.material_id
    cross join normalized
    where normalized.query is not null
      and cb.user_id = target_user_id
      and cb.subject_id = target_subject_id
      and (target_material_ids is null or cb.material_id = any(target_material_ids))
      and (target_block_types is null or cb.block_type = any(target_block_types))
      and (min_confidence is null or coalesce(cb.confidence, 1) >= min_confidence)
      and (
          cb.search_vector @@ websearch_to_tsquery('simple', normalized.query)
          or cb.content_text % normalized.query
          or cb.content_text ilike '%' || normalized.query || '%'
          or cb.structured_data::text ilike '%' || normalized.query || '%'
      )
    order by rank desc, cb.sequence_index
    limit least(greatest(result_limit, 1), 50);
$$;
