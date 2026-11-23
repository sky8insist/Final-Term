begin;
alter table public.material_chunks add column if not exists search_vector tsvector generated always as (to_tsvector('simple',content)) stored;
create index if not exists material_chunk_search_idx on public.material_chunks using gin(search_vector);
create or replace function public.search_content_blocks(
    query_text text,target_user_id uuid,target_subject_id uuid,
    target_material_ids uuid[] default null,target_block_types text[] default null,
    min_confidence double precision default null,result_limit integer default 10
) returns table (
    id uuid,material_id uuid,filename text,block_type text,content_text text,
    structured_data jsonb,page_number integer,bounding_box jsonb,
    start_time double precision,end_time double precision,confidence double precision,rank real
) language sql stable security invoker set search_path=public as $$
    -- child-evidence-v1: whole-block JSON is metadata, not child search text.
    with normalized as (select nullif(trim(query_text),'') as query), units as (
        select cb.id,cb.material_id,m.filename,cb.block_type,cb.content_text,cb.structured_data,
            cb.page_number,cb.bounding_box,cb.start_time,cb.end_time,cb.confidence,cb.search_vector,cb.sequence_index
        from content_blocks cb join materials m on m.id=cb.material_id and m.user_id=cb.user_id and m.subject_id=cb.subject_id
        where m.status='ready' and m.chunk_strategy='baseline' and cb.user_id=target_user_id and cb.subject_id=target_subject_id
        union all
        select cb.id,cb.material_id,m.filename,cb.block_type,c.content,
            cb.structured_data||jsonb_build_object('retrievalChunkId',c.id,'parentChunkId',c.parent_chunk_id,'chunkIndex',c.chunk_index),
            cb.page_number,cb.bounding_box,cb.start_time,cb.end_time,cb.confidence,c.search_vector,c.chunk_index
        from material_chunks c join content_blocks cb on cb.id=c.content_block_id and cb.user_id=c.user_id
            and cb.subject_id=c.subject_id and cb.material_id=c.material_id
        join materials m on m.id=cb.material_id and m.user_id=cb.user_id and m.subject_id=cb.subject_id
        where m.status='ready' and m.chunk_strategy='structure' and c.user_id=target_user_id and c.subject_id=target_subject_id
    ) select u.id,u.material_id,u.filename,u.block_type,u.content_text,u.structured_data,u.page_number,u.bounding_box,
        u.start_time,u.end_time,u.confidence,
        greatest(ts_rank_cd(u.search_vector,websearch_to_tsquery('simple',normalized.query)),
            similarity(u.content_text,normalized.query),similarity(case when u.structured_data ? 'retrievalChunkId' then '' else u.structured_data::text end,normalized.query))::real
    from units u cross join normalized where normalized.query is not null
        and (target_material_ids is null or u.material_id=any(target_material_ids))
        and (target_block_types is null or u.block_type=any(target_block_types))
        and (min_confidence is null or coalesce(u.confidence,1)>=min_confidence)
        and (u.search_vector @@ websearch_to_tsquery('simple',normalized.query) or u.content_text % normalized.query
             or u.content_text ilike '%'||normalized.query||'%' or (not u.structured_data ? 'retrievalChunkId' and u.structured_data::text ilike '%'||normalized.query||'%'))
    order by 12 desc,u.sequence_index,u.id limit least(greatest(result_limit,1),160);
$$;
commit;
