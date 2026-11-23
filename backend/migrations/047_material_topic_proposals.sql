begin;
create table public.material_outlines (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,
 material_id uuid not null,snapshot jsonb not null,sections jsonb not null,
 snapshot_hash text not null,prepared_at timestamptz not null default clock_timestamp(),
 unique(material_id,snapshot_hash),unique(id,user_id,subject_id,material_id),
 foreign key(material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade
);
create table public.material_topic_proposals (
 id uuid primary key default gen_random_uuid(),outline_id uuid not null,user_id uuid not null,
 subject_id uuid not null,material_id uuid not null,source_block_id uuid not null,
 title text not null check(length(trim(title)) between 1 and 300),chapter_title text not null,
 status text not null default 'pending' check(status in ('pending','accepted','rejected')),
 version integer not null default 1 check(version>0),knowledge_point_id uuid,
 unique(outline_id,source_block_id),
 foreign key(outline_id,user_id,subject_id,material_id) references public.material_outlines(id,user_id,subject_id,material_id) on delete cascade,
 foreign key(source_block_id,user_id,subject_id,material_id) references public.content_blocks(id,user_id,subject_id,material_id) on delete cascade,
 foreign key(knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id)
);
create index material_outline_latest_idx on public.material_outlines(user_id,material_id,prepared_at desc,id desc);
alter table public.material_outlines enable row level security;
alter table public.material_topic_proposals enable row level security;
create policy "Read own material outlines" on public.material_outlines for select to authenticated using(user_id=auth.uid());
create policy "Read own material proposals" on public.material_topic_proposals for select to authenticated using(user_id=auth.uid());
revoke all on public.material_outlines,public.material_topic_proposals from public,anon,authenticated;
grant select on public.material_outlines,public.material_topic_proposals to authenticated;
grant all on public.material_outlines,public.material_topic_proposals to service_role;

-- Keep only canonical fields used by the splitter; a change invalidates the batch.
create function public.material_outline_snapshot(p_user uuid,p_material uuid) returns jsonb
language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'block_type',block_type,
   'content_text',content_text,'sequence_index',sequence_index,'page_number',page_number,
   'metadata',metadata,'structured_data',structured_data) order by sequence_index,id),'[]'::jsonb)
 from content_blocks where material_id=p_material and user_id=p_user
$$;

create function public.read_material_outline(p_user uuid,p_material uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare batch material_outlines;
begin
 if not exists(select 1 from materials where id=p_material and user_id=p_user) then
   raise exception 'Material not found' using errcode='42501'; end if;
 select * into batch from material_outlines where material_id=p_material and user_id=p_user
   order by prepared_at desc,id desc limit 1;
 if not found then return null; end if;
 return jsonb_build_object('id',batch.id,'sections',batch.sections,
   'stale',batch.snapshot is distinct from material_outline_snapshot(p_user,p_material)
     or not exists(select 1 from materials where id=p_material and status='ready'),
   'proposals',coalesce((select jsonb_agg(to_jsonb(p)-'user_id' order by b.sequence_index,p.id)
     from material_topic_proposals p join content_blocks b on b.id=p.source_block_id
     where outline_id=batch.id),'[]'::jsonb));
end $$;

create function public.prepare_material_outline(p_user uuid,p_material uuid,p_snapshot jsonb,p_sections jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare mat materials; batch material_outlines; section jsonb; block content_blocks; digest text;
begin
 select * into mat from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material not found' using errcode='42501'; end if;
 if mat.status<>'ready' then raise exception 'Material not ready' using errcode='22023'; end if;
 perform 1 from content_blocks where material_id=p_material and user_id=p_user order by id for share;
 if p_snapshot is null or p_sections is null or octet_length(p_snapshot::text)>4194304
   or jsonb_typeof(p_snapshot)<>'array' or jsonb_array_length(p_snapshot)>2000
   or jsonb_typeof(p_sections)<>'array' or jsonb_array_length(p_sections)>60 then
   raise exception 'Outline too large' using errcode='22023'; end if;
 if p_snapshot is distinct from material_outline_snapshot(p_user,p_material) then
   raise exception 'Source changed' using errcode='40001'; end if;
 -- Sections must partition the entire snapshot in original reading order.
 if (select coalesce(jsonb_agg(x.value order by s.ordinality,x.ordinality),'[]'::jsonb)
     from jsonb_array_elements(p_sections) with ordinality s(value,ordinality),
       jsonb_array_elements(s.value->'blockIds') with ordinality x(value,ordinality))
    is distinct from (select coalesce(jsonb_agg(x.value->'id' order by x.ordinality),'[]'::jsonb)
       from jsonb_array_elements(p_snapshot) with ordinality x(value,ordinality)) then
   raise exception 'Incomplete section membership' using errcode='22023'; end if;
 digest:=md5(p_snapshot::text);
 select * into batch from material_outlines where material_id=p_material and snapshot_hash=digest;
 if not found then
   insert into material_outlines(user_id,subject_id,material_id,snapshot,sections,snapshot_hash)
     values(p_user,mat.subject_id,p_material,p_snapshot,p_sections,digest) returning * into batch;
   for section in select value from jsonb_array_elements(p_sections) loop
     if section->>'sourceBlockId' is null then continue; end if;
     select * into block from content_blocks where id=(section->>'sourceBlockId')::uuid
       and user_id=p_user and subject_id=mat.subject_id and material_id=p_material and block_type='heading';
     if not found or trim(block.content_text) is distinct from section->>'title'
       or section->'blockIds'->>0 is distinct from section->>'sourceBlockId'
       or length(trim(section->>'chapterTitle')) not between 1 and 300 then
       raise exception 'Invalid heading evidence' using errcode='22023'; end if;
     insert into material_topic_proposals(outline_id,user_id,subject_id,material_id,source_block_id,title,chapter_title)
       values(batch.id,p_user,mat.subject_id,p_material,block.id,section->>'title',section->>'chapterTitle');
   end loop;
 end if;
 update material_outlines set prepared_at=clock_timestamp() where id=batch.id;
 return read_material_outline(p_user,p_material);
end $$;

create function public.decide_material_topic(p_user uuid,p_proposal uuid,p_version integer,p_action text,p_title text default null) returns jsonb
language plpgsql security definer set search_path=public as $$
declare proposal material_topic_proposals; batch material_outlines; unit_id uuid; topic knowledge_points; resolved_title text;
begin
 select * into proposal from material_topic_proposals where id=p_proposal and user_id=p_user;
 if not found then raise exception 'Proposal not found' using errcode='42501'; end if;
 perform 1 from materials where id=proposal.material_id and user_id=p_user and status='ready' for update;
 if not found then raise exception 'Material unavailable' using errcode='40001'; end if;
 select * into proposal from material_topic_proposals where id=p_proposal and user_id=p_user for update;
 select * into batch from material_outlines where id=proposal.outline_id;
 perform 1 from content_blocks where material_id=proposal.material_id and user_id=p_user order by id for share;
 if batch.snapshot is distinct from material_outline_snapshot(p_user,proposal.material_id) then
   raise exception 'Source changed' using errcode='40001'; end if;
 if p_action not in ('accept','reject') then raise exception 'Invalid action' using errcode='22023'; end if;
 -- Replays of the same decision return the existing result without new Topics.
 if proposal.status<>'pending' then
   if (p_action='accept' and proposal.status='accepted') or (p_action='reject' and proposal.status='rejected') then
     return to_jsonb(proposal)-'user_id'; end if;
   raise exception 'Proposal already decided' using errcode='40001';
 end if;
 if proposal.version<>p_version then raise exception 'Proposal changed' using errcode='40001'; end if;
 if p_action='accept' then
   resolved_title:=trim(coalesce(p_title,proposal.title));
   if length(resolved_title) not between 1 and 300 then raise exception 'Invalid title' using errcode='22023'; end if;
   -- Same chapter title reuses the existing unit; existing Topic metadata stays intact.
   perform pg_advisory_xact_lock(hashtextextended('outline-unit:'||p_user::text||proposal.subject_id::text||lower(proposal.chapter_title),0));
   select id into unit_id from knowledge_units where user_id=p_user and subject_id=proposal.subject_id
     and lower(trim(knowledge_units.title))=lower(trim(proposal.chapter_title)) order by created_at,id limit 1;
   if unit_id is null then
     insert into knowledge_units(user_id,subject_id,title) values(p_user,proposal.subject_id,proposal.chapter_title) returning id into unit_id;
   end if;
   topic:=resolve_course_topic(p_user,proposal.subject_id,resolved_title,jsonb_build_object('unit_id',unit_id,
     'source_refs',jsonb_build_array(jsonb_build_object('materialId',proposal.material_id,'blockId',proposal.source_block_id,
       'text',proposal.title,'outlineId',batch.id))));
   if topic.archived then raise exception 'Topic archived' using errcode='22023'; end if;
   update material_topic_proposals set status='accepted',version=version+1,title=resolved_title,knowledge_point_id=topic.id
     where id=p_proposal returning * into proposal;
 else
   update material_topic_proposals set status='rejected',version=version+1 where id=p_proposal returning * into proposal;
 end if;
 return to_jsonb(proposal)-'user_id';
end $$;

revoke all on function public.material_outline_snapshot(uuid,uuid) from public,anon,authenticated;
revoke all on function public.read_material_outline(uuid,uuid) from public,anon,authenticated;
revoke all on function public.prepare_material_outline(uuid,uuid,jsonb,jsonb) from public,anon,authenticated;
revoke all on function public.decide_material_topic(uuid,uuid,integer,text,text) from public,anon,authenticated;
grant execute on function public.material_outline_snapshot(uuid,uuid),public.read_material_outline(uuid,uuid),
 public.prepare_material_outline(uuid,uuid,jsonb,jsonb),public.decide_material_topic(uuid,uuid,integer,text,text) to service_role;
notify pgrst,'reload schema';
commit;
