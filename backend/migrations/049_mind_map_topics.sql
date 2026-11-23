begin;
create table public.mind_map_topic_links (
 artifact_id uuid not null,user_id uuid not null,subject_id uuid not null,node_id text not null,
 knowledge_point_id uuid,node_snapshot jsonb not null,version integer not null default 1 check(version>0),
 primary key(artifact_id,node_id),
 foreign key(artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade,
 foreign key(knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id)
);
alter table public.mind_map_topic_links enable row level security;
create policy "Read own map Topic links" on public.mind_map_topic_links for select to authenticated using(user_id=auth.uid());
revoke all on public.mind_map_topic_links from public,anon,authenticated;
grant select on public.mind_map_topic_links to authenticated;
grant all on public.mind_map_topic_links to service_role;

create function public.bind_mind_map_topic(p_user uuid,p_artifact uuid,p_node text,p_topic uuid,p_artifact_version integer,p_binding_version integer)
returns jsonb language plpgsql security definer set search_path=public as $$
declare art artifacts; link mind_map_topic_links; node jsonb; current_version integer;
begin
 select * into art from artifacts where id=p_artifact and user_id=p_user and artifact_type='mind_map' for update;
 if not found then raise exception 'Map not found' using errcode='42501'; end if;
 if art.version<>p_artifact_version then raise exception 'Map changed' using errcode='40001'; end if;
 if (select count(*) from jsonb_array_elements(art.content->'nodes') n where n->>'id'=p_node)<>1 then
   raise exception 'Node not found or ambiguous' using errcode='22023'; end if;
 select n into node from jsonb_array_elements(art.content->'nodes') n where n->>'id'=p_node;
 select * into link from mind_map_topic_links where artifact_id=p_artifact and node_id=p_node;
 current_version:=coalesce(link.version,0);
 if current_version<>p_binding_version then raise exception 'Binding changed' using errcode='40001'; end if;
 if p_topic is not null and not exists(select 1 from knowledge_points where id=p_topic and user_id=p_user
   and subject_id=art.subject_id and not archived) then raise exception 'Topic unavailable' using errcode='22023'; end if;
 insert into mind_map_topic_links(artifact_id,user_id,subject_id,node_id,knowledge_point_id,node_snapshot,version)
   values(p_artifact,p_user,art.subject_id,p_node,p_topic,node,current_version+1)
 on conflict(artifact_id,node_id) do update set knowledge_point_id=excluded.knowledge_point_id,
   node_snapshot=excluded.node_snapshot,version=excluded.version;
 update artifacts set version=version+1 where id=p_artifact returning * into art;
 return jsonb_build_object('artifactVersion',art.version,'bindingVersion',current_version+1);
end $$;

create function public.read_mind_map_learning(p_user uuid,p_artifact uuid) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare art artifacts; output jsonb;
begin
 select * into art from artifacts where id=p_artifact and user_id=p_user and artifact_type='mind_map';
 if not found then raise exception 'Map not found' using errcode='42501'; end if;
 select coalesce(jsonb_object_agg(n->>'id',jsonb_build_object(
   'bindingVersion',coalesce(l.version,0),'knowledgePointId',case when l.node_snapshot=n and not t.archived then t.id end,
   'stale',l.knowledge_point_id is not null and (l.node_snapshot is distinct from n or t.archived),
   'topicTitle',case when l.node_snapshot=n and not t.archived then t.title end,
   'mastery',case when l.node_snapshot=n and not t.archived then to_jsonb(m) end,
   'covered',case when l.node_snapshot=n and not t.archived then cv.knowledge_point_id is not null else false end,
   'dueCards',case when l.node_snapshot=n and not t.archived then (
     select count(*) from flashcards c join flashcard_review_state s on s.artifact_id=c.artifact_id and s.card_id=c.card_id
     where c.user_id=p_user and c.subject_id=art.subject_id and c.knowledge_point_id=t.id and not c.archived and s.next_review<=now()
   ) else 0 end,
   'exams',case when l.node_snapshot=n and not t.archived then coalesce((
     select jsonb_agg(jsonb_build_object('id',e.id,'title',e.title,'date',e.exam_date,'weight',et.weight) order by e.exam_date,e.id)
     from exam_topic_map et join exam_events e on e.id=et.exam_event_id and e.user_id=p_user and e.subject_id=art.subject_id
     where et.user_id=p_user and et.subject_id=art.subject_id and et.knowledge_point_id=t.id and e.status='active'
       and e.exam_date>=(now() at time zone 'Asia/Shanghai')::date),'[]'::jsonb) else '[]'::jsonb end
 )),'{}'::jsonb) into output
 from jsonb_array_elements(art.content->'nodes') n
 left join mind_map_topic_links l on l.artifact_id=art.id and l.user_id=p_user and l.node_id=n->>'id'
 left join knowledge_points t on t.id=l.knowledge_point_id and t.user_id=p_user and t.subject_id=art.subject_id
 left join knowledge_mastery m on m.user_id=p_user and m.subject_id=art.subject_id and m.knowledge_key=t.knowledge_key
 left join topic_coverage cv on cv.user_id=p_user and cv.subject_id=art.subject_id and cv.knowledge_point_id=t.id;
 return jsonb_build_object('artifactVersion',art.version,'nodes',output);
end $$;
revoke all on function public.bind_mind_map_topic(uuid,uuid,text,uuid,integer,integer),public.read_mind_map_learning(uuid,uuid) from public,anon,authenticated;
grant execute on function public.bind_mind_map_topic(uuid,uuid,text,uuid,integer,integer),public.read_mind_map_learning(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
