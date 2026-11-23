begin;
create table public.workspace_cache_versions (
 user_id uuid not null references auth.users(id) on delete cascade,scope_id uuid not null,resource text not null,
 revision uuid not null default gen_random_uuid(),version bigint not null default 1,primary key(user_id,scope_id,resource)
);
alter table workspace_cache_versions enable row level security;
create policy "Read own cache versions" on workspace_cache_versions for select to authenticated using(user_id=auth.uid());
revoke all on workspace_cache_versions from public,anon,authenticated;
grant select on workspace_cache_versions to authenticated;
grant all on workspace_cache_versions to service_role;
create function public.bump_workspace_versions(p_user uuid,p_subject uuid,p_resources text[]) returns void
language plpgsql security definer set search_path=public as $$
declare res_name text;scope uuid;
begin
 if not exists(select 1 from auth.users where id=p_user) then return;end if;
 foreach res_name in array p_resources loop
  scope:=case when res_name in ('dashboard','subjects','workspace') then '00000000-0000-0000-0000-000000000000'::uuid else p_subject end;
  if scope is null then continue;end if;
  if scope<>'00000000-0000-0000-0000-000000000000'::uuid and not exists(select 1 from subjects where id=scope and user_id=p_user) then continue;end if;
  insert into workspace_cache_versions(user_id,scope_id,resource) values(p_user,scope,res_name)
  on conflict(user_id,scope_id,resource) do update set revision=gen_random_uuid(),version=workspace_cache_versions.version+1;
 end loop;
end $$;
create function public.track_workspace_version() returns trigger language plpgsql security definer set search_path=public as $$
declare item jsonb;uid uuid;sid uuid;resources text[];
begin
 item:=case when tg_op='DELETE' then to_jsonb(old) else to_jsonb(new) end;
 if tg_op='UPDATE' and (item-'updated_at')=(to_jsonb(old)-'updated_at') then return null;end if;
 uid:=(item->>'user_id')::uuid;sid:=(item->>'subject_id')::uuid;
 case tg_table_name
 when 'subjects' then
  sid:=(item->>'id')::uuid;resources:=array['subjects','dashboard','workspace'];
  if tg_op='DELETE' then delete from workspace_cache_versions where user_id=uid and scope_id=sid;end if;
 when 'learning_domain_events' then
  case item->>'event_type'
  when 'mastery.changed' then resources:=array['dashboard','plan','mind-map','recommendations'];
  when 'exam.completed' then resources:=array['dashboard','plan','mind-map','exams','recommendations'];
  when 'material.indexed' then resources:=array['dashboard','plan','mind-map','recommendations'];
  when 'flashcard.reviewed' then resources:=array['dashboard','plan','mind-map','recommendations'];
  when 'exam.updated' then resources:=array['dashboard','plan','exams','recommendations'];
  else resources:=array['dashboard','plan','recommendations'];end case;
 when 'chat_messages' then resources:=array['chat'];
 when 'exams' then resources:=array['exams'];
 when 'exam_attempts' then resources:=array['dashboard','exams','plan','recommendations'];
 when 'artifacts' then
  if item->>'artifact_type'='mind_map' then resources:=array['mind-map'];else resources:=array['dashboard','plan','mind-map','recommendations'];end if;
 when 'materials' then resources:=array['mind-map','plan','recommendations'];
 when 'mind_map_topic_links' then resources:=array['mind-map'];
 when 'learner_profiles' then resources:=array['dashboard'];
 else resources:=array['dashboard','plan','mind-map','recommendations'];end case;
 perform bump_workspace_versions(uid,sid,resources);return null;
end $$;
create trigger workspace_event_version after insert on learning_domain_events for each row execute function track_workspace_version();
do $$ declare tab text;begin
 foreach tab in array array['subjects','chat_messages','study_plans','review_tasks','knowledge_points','knowledge_units','topic_coverage',
   'review_progress','knowledge_mastery','exam_attempts','flashcards','flashcard_review_state','artifacts','mind_map_topic_links','exams','materials','learner_profiles','calendar_availability'] loop
 execute format('create trigger workspace_resource_version after insert or update or delete on public.%I for each row execute function track_workspace_version()',tab);
 end loop;
end $$;
create function public.workspace_resource_version(p_user uuid,p_resource text,p_subject uuid default null) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare scope uuid;revision text;bucket text;epoch bigint;
begin
 if p_resource not in ('dashboard','subjects','workspace','chat','mind-map','exams','plan','recommendations') then raise exception 'Unsupported resource' using errcode='22023';end if;
 if p_resource in ('dashboard','subjects','workspace') then
  if p_subject is not null then raise exception 'Global resource cannot have subject' using errcode='22023';end if;
  scope:='00000000-0000-0000-0000-000000000000'::uuid;
 else
  if p_subject is null then raise exception 'Subject required' using errcode='22023';end if;
  if not exists(select 1 from subjects where id=p_subject and user_id=p_user) then raise exception 'Subject unavailable' using errcode='42501';end if;
  scope:=p_subject;
 end if;
 select v.revision::text into revision from workspace_cache_versions v where user_id=p_user and scope_id=scope and resource=p_resource;
 bucket:=case when p_resource in ('dashboard','plan','mind-map','recommendations','exams') then to_char(now() at time zone 'Asia/Shanghai','YYYY-MM-DD HH24:MI') else '' end;
 select coalesce(max(v.version),0) into epoch from learning_projection_versions v where v.user_id=p_user and (p_subject is null or v.subject_id=p_subject);
 return jsonb_build_object('schemaVersion',2,'resource',p_resource,'subjectId',p_subject,
  'version',md5(jsonb_build_array('workspace-v2:learner-state-v1',p_user,scope,p_resource,coalesce(revision,'0'),bucket)::text),
  'dataVersion',md5(jsonb_build_array(p_user,scope,p_resource,coalesce(revision,'0'))::text),'projectionVersion',epoch,'timeBucket',bucket);
end $$;
create function public.revoke_workspace_snapshots(p_user uuid) returns void language plpgsql security definer set search_path=public as $$
begin
 delete from workspace_cache_versions where user_id=p_user;
 insert into workspace_cache_versions(user_id,scope_id,resource)
 select p_user,'00000000-0000-0000-0000-000000000000'::uuid,resource from unnest(array['dashboard','subjects','workspace']) resource;
 insert into workspace_cache_versions(user_id,scope_id,resource)
 select p_user,s.id,resource from subjects s cross join unnest(array['chat','mind-map','exams','plan','recommendations']) resource where s.user_id=p_user;
end $$;
revoke all on function public.bump_workspace_versions(uuid,uuid,text[]),public.workspace_resource_version(uuid,text,uuid),public.revoke_workspace_snapshots(uuid) from public,anon,authenticated;
grant execute on function public.workspace_resource_version(uuid,text,uuid),public.revoke_workspace_snapshots(uuid) to service_role;
notify pgrst,'reload schema';
commit;
