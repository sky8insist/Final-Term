begin;
alter table public.materials add constraint materials_chunk_scope_unique unique(id,user_id,subject_id);
alter table public.content_blocks add constraint content_blocks_chunk_scope_unique unique(id,user_id,subject_id,material_id);
alter table public.materials add column chunk_strategy text not null default 'baseline' check(chunk_strategy in ('baseline','structure'));
create table public.parent_chunks (
    id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,material_id uuid not null,
    parent_index integer not null check(parent_index>=0),heading_path jsonb not null default '[]' check(jsonb_typeof(heading_path)='array'),
    content text not null,strategy_version text not null,created_at timestamptz not null default now(),
    unique(material_id,parent_index),unique(id,user_id,subject_id,material_id),
    foreign key(material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade
);
create table public.parent_chunk_blocks (
    parent_chunk_id uuid not null,content_block_id uuid not null,user_id uuid not null,subject_id uuid not null,material_id uuid not null,
    sequence_index integer not null check(sequence_index>=0),primary key(parent_chunk_id,content_block_id),
    unique(parent_chunk_id,content_block_id,user_id,subject_id,material_id),
    foreign key(parent_chunk_id,user_id,subject_id,material_id) references public.parent_chunks(id,user_id,subject_id,material_id) on delete cascade,
    foreign key(content_block_id,user_id,subject_id,material_id) references public.content_blocks(id,user_id,subject_id,material_id) on delete cascade
);
create index parent_members_block_idx on public.parent_chunk_blocks(user_id,subject_id,material_id,content_block_id);
alter table public.material_chunks add column parent_chunk_id uuid;
alter table public.material_chunks add constraint child_parent_member_fk
    foreign key(parent_chunk_id,content_block_id,user_id,subject_id,material_id)
    references public.parent_chunk_blocks(parent_chunk_id,content_block_id,user_id,subject_id,material_id) on delete cascade;
create index child_parent_idx on public.material_chunks(parent_chunk_id);
alter table public.parent_chunks enable row level security;
alter table public.parent_chunk_blocks enable row level security;
create policy "Owners read parent chunks" on public.parent_chunks for select to authenticated using(user_id=auth.uid());
create policy "Owners read parent members" on public.parent_chunk_blocks for select to authenticated using(user_id=auth.uid());

create function public.replace_material_chunk_bundle(p_user_id uuid,p_subject_id uuid,p_material_id uuid,
    p_strategy text,p_parents jsonb,p_records jsonb) returns jsonb language plpgsql set search_path=public as $$
declare material public.materials; parent jsonb; child jsonb; block public.content_blocks; bid text; ordinal bigint;
begin
    select * into material from materials where id=p_material_id and user_id=p_user_id and subject_id=p_subject_id for update;
    if not found then raise exception 'Material not found' using errcode='42501'; end if;
    if p_strategy not in ('baseline','structure') or jsonb_typeof(p_parents)<>'array' or jsonb_typeof(p_records)<>'array'
        or jsonb_array_length(p_records)=0 then raise exception 'Invalid chunk bundle' using errcode='23514'; end if;
    if p_strategy='baseline' and jsonb_array_length(p_parents)>0 then raise exception 'Baseline cannot have parents' using errcode='23514'; end if;
    delete from material_chunks where material_id=p_material_id and user_id=p_user_id and subject_id=p_subject_id;
    delete from parent_chunks where material_id=p_material_id and user_id=p_user_id and subject_id=p_subject_id;
    for parent in select value from jsonb_array_elements(p_parents) loop
        if jsonb_array_length(parent->'block_ids')=0 then raise exception 'Empty parent' using errcode='23514'; end if;
        insert into parent_chunks(id,user_id,subject_id,material_id,parent_index,heading_path,content,strategy_version)
            values((parent->>'id')::uuid,p_user_id,p_subject_id,p_material_id,(parent->>'parent_index')::integer,
                parent->'heading_path','',parent->>'strategy_version');
        for bid,ordinal in select value,ordinality from jsonb_array_elements_text(parent->'block_ids') with ordinality loop
            insert into parent_chunk_blocks(parent_chunk_id,content_block_id,user_id,subject_id,material_id,sequence_index)
                values((parent->>'id')::uuid,bid::uuid,p_user_id,p_subject_id,p_material_id,ordinal-1);
        end loop;
        update parent_chunks set content=(select string_agg(b.content_text,E'\n\n' order by pb.sequence_index)
            from parent_chunk_blocks pb join content_blocks b on b.id=pb.content_block_id where pb.parent_chunk_id=(parent->>'id')::uuid)
            where id=(parent->>'id')::uuid;
    end loop;
    for child in select value from jsonb_array_elements(p_records) loop
        select * into block from content_blocks where id=(child->>'content_block_id')::uuid
            and user_id=p_user_id and subject_id=p_subject_id and material_id=p_material_id;
        if not found then raise exception 'Block scope mismatch' using errcode='42501'; end if;
        if (p_strategy='structure')<>(nullif(child->>'parent_chunk_id','') is not null) then
            raise exception 'Parent strategy mismatch' using errcode='23514'; end if;
        insert into material_chunks(user_id,subject_id,material_id,chunk_index,content,metadata,content_block_id,
            block_type,page_number,bounding_box,start_time,end_time,parent_chunk_id)
        values(p_user_id,p_subject_id,p_material_id,(child->>'chunk_index')::integer,child->>'content',
            coalesce(child->'metadata','{}')||jsonb_build_object('strategy',p_strategy),block.id,block.block_type,
            block.page_number,block.bounding_box,block.start_time,block.end_time,(child->>'parent_chunk_id')::uuid);
    end loop;
    update materials set chunk_strategy=p_strategy,status='parsing' where id=p_material_id;
    return (select jsonb_agg(to_jsonb(c)-'embedding' order by chunk_index) from material_chunks c where material_id=p_material_id and user_id=p_user_id and subject_id=p_subject_id);
end; $$;
revoke all on function public.replace_material_chunk_bundle(uuid,uuid,uuid,text,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.replace_material_chunk_bundle(uuid,uuid,uuid,text,jsonb,jsonb) to service_role;

-- Return canonical, scoped members. Caller applies every retrieval filter before
-- selecting context; cached parent text is never used as evidence authority.
create function public.parent_context_blocks(p_user_id uuid,p_subject_id uuid,p_block_ids uuid[])
returns jsonb language sql stable set search_path=public as $$
    with members as (
        select a.content_block_id as anchor,p.id as parent_id,p.heading_path,b.*,pb.sequence_index as ordinal
        from parent_chunk_blocks a join parent_chunks p on p.id=a.parent_chunk_id
        join parent_chunk_blocks pb on pb.parent_chunk_id=p.id join content_blocks b on b.id=pb.content_block_id
        join materials m on m.id=p.material_id
        where a.content_block_id=any(p_block_ids) and p.user_id=p_user_id and p.subject_id=p_subject_id
            and b.user_id=p_user_id and b.subject_id=p_subject_id and b.material_id=p.material_id
            and m.user_id=p_user_id and m.subject_id=p_subject_id and m.status='ready'
        union all
        select a.id,null::uuid,'[]'::jsonb,b.*,b.sequence_index
        from content_blocks a join materials m on m.id=a.material_id
        join content_blocks b on b.material_id=a.material_id and b.page_number=a.page_number
        where a.id=any(p_block_ids) and a.user_id=p_user_id and a.subject_id=p_subject_id
            and b.user_id=p_user_id and b.subject_id=p_subject_id
            and m.user_id=p_user_id and m.subject_id=p_subject_id and m.status='ready' and m.chunk_strategy='baseline'
    ) select coalesce(jsonb_agg(jsonb_build_object('anchorBlockId',anchor,'parentChunkId',parent_id,
        'headingPath',heading_path,'blockId',id,'materialId',material_id,'blockType',block_type,
        'text',content_text,'pageNumber',page_number,'boundingBox',bounding_box,'startTime',start_time,
        'endTime',end_time,'confidence',confidence,'sequence',ordinal)
        order by anchor,parent_id,ordinal),'[]') from members;
$$;
revoke all on function public.parent_context_blocks(uuid,uuid,uuid[]) from public,anon,authenticated;
grant execute on function public.parent_context_blocks(uuid,uuid,uuid[]) to service_role;
create or replace function public.search_content_blocks(
    query_text text,target_user_id uuid,target_subject_id uuid,
    target_material_ids uuid[] default null,target_block_types text[] default null,
    min_confidence double precision default null,result_limit integer default 10
) returns table (
    id uuid,material_id uuid,filename text,block_type text,content_text text,
    structured_data jsonb,page_number integer,bounding_box jsonb,
    start_time double precision,end_time double precision,confidence double precision,rank real
) language sql stable security invoker set search_path=public as $$
    with normalized as (select nullif(trim(query_text),'') as query)
    select cb.id,cb.material_id,m.filename,cb.block_type,cb.content_text,
        cb.structured_data,cb.page_number,cb.bounding_box,cb.start_time,cb.end_time,cb.confidence,
        greatest(ts_rank_cd(cb.search_vector,websearch_to_tsquery('simple',normalized.query)),
                 similarity(cb.content_text,normalized.query),similarity(cb.structured_data::text,normalized.query))::real
    from content_blocks cb join materials m on m.id=cb.material_id and m.user_id=cb.user_id and m.subject_id=cb.subject_id
    cross join normalized where normalized.query is not null and m.status='ready'
        and cb.user_id=target_user_id and cb.subject_id=target_subject_id
        and (m.chunk_strategy='baseline' or exists(select 1 from parent_chunk_blocks pb where pb.content_block_id=cb.id and pb.user_id=cb.user_id and pb.subject_id=cb.subject_id and pb.material_id=cb.material_id))
        and (target_material_ids is null or cb.material_id=any(target_material_ids))
        and (target_block_types is null or cb.block_type=any(target_block_types))
        and (min_confidence is null or coalesce(cb.confidence,1)>=min_confidence)
        and (cb.search_vector @@ websearch_to_tsquery('simple',normalized.query)
             or cb.content_text % normalized.query or cb.content_text ilike '%'||normalized.query||'%'
             or cb.structured_data::text ilike '%'||normalized.query||'%')
    order by 12 desc,cb.sequence_index,cb.id limit least(greatest(result_limit,1),160);
$$;
commit;
