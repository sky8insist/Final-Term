begin;
create table public.lectures (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,material_id uuid not null,
 title text not null check(length(trim(title)) between 1 and 300),
 source_kind text not null check(source_kind in ('recording','upload')),
 version integer not null default 1 check(version>0),created_at timestamptz not null default now(),
 unique(user_id,material_id),unique(id,user_id,subject_id,material_id),
 foreign key(material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade
);
create table public.lecture_topic_links (
 lecture_id uuid not null,user_id uuid not null,subject_id uuid not null,material_id uuid not null,
 block_id uuid not null,knowledge_point_id uuid not null,source_text text not null,start_time double precision,end_time double precision,
 primary key(lecture_id,block_id),
 foreign key(lecture_id,user_id,subject_id,material_id) references public.lectures(id,user_id,subject_id,material_id) on delete cascade,
 foreign key(block_id,user_id,subject_id,material_id) references public.content_blocks(id,user_id,subject_id,material_id) on delete cascade,
 foreign key(knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id)
);
alter table public.lectures enable row level security;
alter table public.lecture_topic_links enable row level security;
create policy "Read own lectures" on public.lectures for select to authenticated using(user_id=auth.uid());
create policy "Read own lecture links" on public.lecture_topic_links for select to authenticated using(user_id=auth.uid());
revoke all on public.lectures,public.lecture_topic_links from public,anon,authenticated;
grant select on public.lectures,public.lecture_topic_links to authenticated;
grant all on public.lectures,public.lecture_topic_links to service_role;

create function public.attach_lecture(p_user uuid,p_subject uuid,p_material uuid,p_title text,p_kind text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved public.lectures;
begin
 perform pg_advisory_xact_lock(hashtextextended('lecture:'||p_user::text||p_material::text,0));
 if not exists(select 1 from materials where id=p_material and user_id=p_user and subject_id=p_subject
  and content_type in ('audio/mpeg','audio/wav','audio/x-wav','audio/mp4','audio/x-m4a','audio/webm')) then
  raise exception 'Audio material not found' using errcode='42501'; end if;
 select * into saved from lectures where user_id=p_user and material_id=p_material;
 if found then return to_jsonb(saved)-'user_id'; end if;
 insert into lectures(user_id,subject_id,material_id,title,source_kind) values(p_user,p_subject,p_material,p_title,p_kind) returning * into saved;
 return to_jsonb(saved)-'user_id';
end $$;

create function public.align_lecture_topic(p_user uuid,p_lecture uuid,p_block uuid,p_topic uuid,p_version integer) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved public.lectures; block public.content_blocks;
begin
 select * into saved from lectures where id=p_lecture and user_id=p_user for update;
 if not found then raise exception 'Lecture not found' using errcode='42501'; end if;
 if saved.version<>p_version then raise exception 'Lecture changed' using errcode='40001'; end if;
 if not exists(select 1 from materials where id=saved.material_id and status='ready') then raise exception 'Transcript not ready' using errcode='22023'; end if;
 select * into block from content_blocks where id=p_block and material_id=saved.material_id and user_id=p_user and subject_id=saved.subject_id and block_type='audio';
 if not found then raise exception 'Transcript block not found' using errcode='42501'; end if;
 if p_topic is not null then
  if not exists(select 1 from knowledge_points where id=p_topic and user_id=p_user and subject_id=saved.subject_id and not archived) then
   raise exception 'Topic unavailable' using errcode='22023'; end if;
  insert into lecture_topic_links(lecture_id,user_id,subject_id,material_id,block_id,knowledge_point_id,source_text,start_time,end_time)
   values(saved.id,p_user,saved.subject_id,saved.material_id,p_block,p_topic,block.content_text,block.start_time,block.end_time)
   on conflict(lecture_id,block_id) do update set knowledge_point_id=excluded.knowledge_point_id,source_text=excluded.source_text,start_time=excluded.start_time,end_time=excluded.end_time;
 else delete from lecture_topic_links where lecture_id=p_lecture and block_id=p_block;
 end if;
 update lectures set version=version+1 where id=p_lecture returning * into saved;
 return to_jsonb(saved)-'user_id';
end $$;

create function public.lecture_transcript(p_user uuid,p_lecture uuid,p_offset integer default 0,p_limit integer default 50,p_block uuid default null) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved public.lectures; output jsonb; count_all integer;
begin
 select * into saved from lectures where id=p_lecture and user_id=p_user;
 if not found then raise exception 'Lecture not found' using errcode='42501'; end if;
 if p_offset<0 or p_limit not between 1 and 100 then raise exception 'Invalid transcript page' using errcode='22023'; end if;
 if p_block is not null then
  if not exists(select 1 from content_blocks where id=p_block and user_id=p_user and material_id=saved.material_id and block_type='audio') then
   raise exception 'Transcript block not found' using errcode='42501'; end if;
  select count(*)/p_limit*p_limit into p_offset from content_blocks b join content_blocks target on target.id=p_block
   where b.user_id=p_user and b.material_id=saved.material_id and b.block_type='audio' and (b.sequence_index,b.id)<(target.sequence_index,target.id);
 end if;
 select count(*) into count_all from content_blocks where user_id=p_user and material_id=saved.material_id and block_type='audio';
 select coalesce(jsonb_agg(to_jsonb(row) order by row.sequence_index,row.id),'[]') into output from (
  select b.id,b.content_text,b.start_time,b.end_time,b.confidence,b.sequence_index,b.structured_data->>'timestampPrecision' as timestamp_precision,
   k.id as knowledge_point_id,k.title as topic_title
  from content_blocks b left join lecture_topic_links l on l.lecture_id=p_lecture and l.block_id=b.id
   and l.source_text=b.content_text and l.start_time is not distinct from b.start_time and l.end_time is not distinct from b.end_time
  left join knowledge_points k on k.id=l.knowledge_point_id and not k.archived
  where b.user_id=p_user and b.material_id=saved.material_id and b.block_type='audio'
  order by b.sequence_index,b.id offset p_offset limit p_limit
 ) row;
 return jsonb_build_object('version',saved.version,'total',count_all,'offset',p_offset,'blocks',output);
end $$;

revoke all on function public.attach_lecture(uuid,uuid,uuid,text,text),public.align_lecture_topic(uuid,uuid,uuid,uuid,integer),public.lecture_transcript(uuid,uuid,integer,integer,uuid) from public,anon,authenticated;
grant execute on function public.attach_lecture(uuid,uuid,uuid,text,text),public.align_lecture_topic(uuid,uuid,uuid,uuid,integer),public.lecture_transcript(uuid,uuid,integer,integer,uuid) to service_role;
notify pgrst,'reload schema';
commit;
