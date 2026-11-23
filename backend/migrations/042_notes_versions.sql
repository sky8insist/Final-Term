begin;
alter table public.artifacts drop constraint artifact_type_check;
alter table public.artifacts add constraint artifact_type_check check
 (artifact_type in ('outline','mind_map','flashcards','formula_sheet','glossary','comparison','cheat_sheet','notes'));

create table public.artifact_versions (
 artifact_id uuid not null, user_id uuid not null, subject_id uuid not null,
 version integer not null check(version > 0), snapshot jsonb not null,
 created_at timestamptz not null default now(), primary key(artifact_id,version),
 foreign key(artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade
);
create table public.note_sources (
 artifact_id uuid not null, user_id uuid not null, subject_id uuid not null,
 content_block_id uuid not null, material_id uuid not null,
 primary key(artifact_id,content_block_id),
 foreign key(artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade,
 foreign key(content_block_id,user_id,subject_id,material_id)
 references public.content_blocks(id,user_id,subject_id,material_id) on delete cascade,
 foreign key(material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade
);
alter table public.artifact_versions enable row level security;
alter table public.note_sources enable row level security;
create policy "Owners read artifact versions" on public.artifact_versions for select to authenticated using(user_id=auth.uid());
create policy "Owners read note sources" on public.note_sources for select to authenticated using(user_id=auth.uid());
revoke all on public.artifact_versions, public.note_sources from anon, authenticated;
grant select on public.artifact_versions, public.note_sources to authenticated;
grant all on public.artifact_versions, public.note_sources to service_role;

drop policy "Users manage own artifacts" on public.artifacts;
create policy "Owners read artifacts" on public.artifacts for select to authenticated using(user_id=auth.uid());
create policy "Owners insert legacy artifacts" on public.artifacts for insert to authenticated
 with check(user_id=auth.uid() and artifact_type <> 'notes');
create policy "Owners update legacy artifacts" on public.artifacts for update to authenticated
 using(user_id=auth.uid() and artifact_type <> 'notes') with check(user_id=auth.uid() and artifact_type <> 'notes');
create policy "Owners delete legacy artifacts" on public.artifacts for delete to authenticated
 using(user_id=auth.uid() and artifact_type <> 'notes');
drop policy "Users manage own artifact topics" on public.artifact_topics;
create policy "Owners read artifact topics" on public.artifact_topics for select to authenticated using(user_id=auth.uid());
create policy "Owners manage legacy artifact topics" on public.artifact_topics for all to authenticated
 using(user_id=auth.uid() and exists(select 1 from public.artifacts a where a.id=artifact_id and a.artifact_type<>'notes'))
 with check(user_id=auth.uid() and exists(select 1 from public.artifacts a where a.id=artifact_id and a.artifact_type<>'notes'));

create function public.snapshot_note_version() returns trigger language plpgsql security definer set search_path=public as $$
begin
 if new.artifact_type='notes' then
  insert into public.artifact_versions(artifact_id,user_id,subject_id,version,snapshot)
  values(new.id,new.user_id,new.subject_id,new.version,to_jsonb(new));
 end if;
 return new;
end $$;
create trigger notes_version_snapshot after insert or update on public.artifacts
 for each row execute function public.snapshot_note_version();

create function public.note_source_citations(p_user_id uuid,p_subject_id uuid,p_block_ids uuid[])
returns jsonb language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(jsonb_build_object('id',b.id,'materialId',b.material_id,
  'filename',m.filename,'sourceName',m.filename,'chunkText',b.content_text,'blockType',b.block_type,
  'pageNumber',b.page_number,'startTime',b.start_time,'endTime',b.end_time,'boundingBox',b.bounding_box)
  order by b.material_id,b.sequence_index,b.id),'[]'::jsonb)
 from public.content_blocks b join public.materials m on m.id=b.material_id
 where b.id=any(p_block_ids) and b.user_id=p_user_id and b.subject_id=p_subject_id
 and m.user_id=p_user_id and m.subject_id=p_subject_id and m.status='ready'
$$;

create or replace function public.save_note(p_user_id uuid,p_subject_id uuid,p_note_id uuid,
 p_expected_version integer,p_values jsonb) returns jsonb language plpgsql security definer set search_path=public as $$
declare
 current_note public.artifacts; saved public.artifacts; source_citations jsonb; section jsonb;
 block_ids uuid[]; topic_ids uuid[]; params jsonb; mode text;
begin
 if not exists(select 1 from public.subjects where id=p_subject_id and user_id=p_user_id) then
  raise exception 'Note not found' using errcode='42501';
 end if;
 if p_note_id is not null then
  select * into current_note from public.artifacts where id=p_note_id and user_id=p_user_id
   and subject_id=p_subject_id and artifact_type='notes' for update;
  if not found then raise exception 'Note not found' using errcode='42501'; end if;
  if p_expected_version is null or current_note.version<>p_expected_version then
   raise exception 'Note version conflict' using errcode='40001';
  end if;
 end if;
 mode:=p_values->>'mode';
 if mode is null or mode not in ('summary','standard','comprehensive','exam_focus') then
  raise exception 'Invalid notes mode' using errcode='22023';
 end if;
 if length(trim(coalesce(p_values->>'title',''))) not between 1 and 300
  or jsonb_typeof(p_values->'content'->'sections') is distinct from 'array' then
  raise exception 'Invalid note content' using errcode='22023';
 end if;
 if jsonb_array_length(p_values->'content'->'sections') not between 1 and 100
  or length((p_values->'content')::text)>250000 then
  raise exception 'Invalid note size' using errcode='22023';
 end if;
 select array_agg(distinct v::uuid) into block_ids from jsonb_array_elements_text(p_values->'citationIds') t(v);
 if coalesce(cardinality(block_ids),0)=0 then raise exception 'Note requires sources' using errcode='22023'; end if;
 source_citations:=public.note_source_citations(p_user_id,p_subject_id,block_ids);
 if jsonb_array_length(source_citations)<>cardinality(block_ids) then
  raise exception 'Note sources unavailable or outside scope' using errcode='22023';
 end if;
 if (select count(distinct value->>'id') from jsonb_array_elements(p_values->'content'->'sections'))
  <>jsonb_array_length(p_values->'content'->'sections') then
  raise exception 'Duplicate note section IDs' using errcode='22023';
 end if;
 for section in select value from jsonb_array_elements(p_values->'content'->'sections') loop
  if jsonb_typeof(section->'body') is distinct from 'string' or jsonb_typeof(section->'title') is distinct from 'string'
   or length(trim(coalesce(section->>'id',''))) not between 1 and 100
   or length(trim(section->>'title')) not between 1 and 300
   or length(trim(section->>'body')) not between 1 and 20000
   or jsonb_typeof(section->'citationIds') is distinct from 'array' then
   raise exception 'Invalid note section' using errcode='22023';
  end if;
  if jsonb_array_length(section->'citationIds')=0 or exists(
    select 1 from jsonb_array_elements_text(section->'citationIds') t(v) where not v::uuid=any(block_ids)) then
   raise exception 'Invalid note citation' using errcode='22023';
  end if;
 end loop;
 select coalesce(array_agg(distinct v::uuid),'{}'::uuid[]) into topic_ids
  from jsonb_array_elements_text(coalesce(p_values->'topicIds','[]'::jsonb)) t(v);
 if (select count(*) from public.knowledge_points where id=any(topic_ids)
   and user_id=p_user_id and subject_id=p_subject_id and not archived) <> cardinality(topic_ids) then
  raise exception 'Note topics unavailable or outside scope' using errcode='22023';
 end if;
 params:=coalesce(p_values->'generationParams','{}'::jsonb)||jsonb_build_object('mode',mode,'knowledgePointIds',to_jsonb(topic_ids));
 if p_note_id is null then
  insert into public.artifacts(user_id,subject_id,artifact_type,title,content,citations,generation_params,model_name,prompt_version)
  values(p_user_id,p_subject_id,'notes',p_values->>'title',p_values->'content',source_citations,params,p_values->>'modelName','notes-v1') returning * into saved;
 else
  update public.artifacts set title=p_values->>'title',content=p_values->'content',citations=source_citations,
   generation_params=params,version=version+1,is_user_edited=true where id=p_note_id returning * into saved;
 end if;
 delete from public.artifact_topics where artifact_id=saved.id;
 insert into public.artifact_topics(artifact_id,user_id,subject_id,knowledge_point_id)
  select saved.id,p_user_id,p_subject_id,id from unnest(topic_ids) t(id);
 delete from public.note_sources where artifact_id=saved.id;
 insert into public.note_sources(artifact_id,user_id,subject_id,content_block_id,material_id)
  select saved.id,p_user_id,p_subject_id,b.id,b.material_id from public.content_blocks b where b.id=any(block_ids);
 return to_jsonb(saved)-'user_id';
end $$;

revoke all on function public.snapshot_note_version() from public,anon,authenticated;
revoke all on function public.note_source_citations(uuid,uuid,uuid[]) from public,anon,authenticated;
revoke all on function public.save_note(uuid,uuid,uuid,integer,jsonb) from public,anon,authenticated;
grant execute on function public.note_source_citations(uuid,uuid,uuid[]),public.save_note(uuid,uuid,uuid,integer,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
