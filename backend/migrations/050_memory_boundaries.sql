begin;
alter table public.memory_entries add column memory_kind text not null default 'legacy',add column provenance jsonb not null default '{}';
alter table public.memory_write_requests add column memory_kind text not null default 'legacy',add column provenance jsonb not null default '{}';
alter table public.memory_snapshots add column policy_version text,add column teaching_profile jsonb not null default '{}',add column manifest jsonb not null default '[]';
alter table public.memory_entries drop constraint memory_entry_unique;
create unique index memory_scope_content_unique on public.memory_entries(user_id,target,coalesce(subject_id,'00000000-0000-0000-0000-000000000000'::uuid),content_hash);

create function public.classify_stable_memory(value text) returns text language sql immutable set search_path=public as $$
 select case
 when value ~* 'mastery|accuracy|score|confidence|due.?review|next review|exam.?date|exam.?result|tomorrow|today|next week|掌握度|已掌握|掌握了|答对|答错|正确率|准确率|得分|分数|信心|复习到期|下次复习|考试日期|考试成绩|考试目标|明天|后天|今天|本周|下周|这次考试|[0-9]{4}[-/年][0-9]|[0-9]+\s*[%％]' then null
 when value ~* '偏好|喜欢|不喜欢|讲解方式|表达方式|prefer|teaching style' then 'preference'
 when value ~* '习惯|通常|每次学习|habit|usually' then 'habit'
 when value ~* '长期.*困难|经常.*困难|总是.*困难|persistent difficulty|often struggle' then 'difficulty'
 when value ~* '长期目标|长远目标|long.term goal' then 'long_term_goal'
 end
$$;

create function public.guard_stable_memory() returns trigger language plpgsql set search_path=public as $$
declare kind text;
begin
 if new.subject_id is not null and not exists(select 1 from subjects where id=new.subject_id and user_id=new.user_id) then
   raise exception 'Subject unavailable' using errcode='42501'; end if;
 if new.source_event_id is not null and not exists(select 1 from learning_events where id=new.source_event_id and user_id=new.user_id and subject_id is not distinct from new.subject_id) then
   raise exception 'Source unavailable' using errcode='42501'; end if;
 if tg_table_name='memory_write_requests' and to_jsonb(new)->>'action'='remove' then kind:='removal';
 else kind:=classify_stable_memory(new.content);
   if kind is null then raise exception 'Only stable teaching memory is allowed' using errcode='22023'; end if;
 end if;
 new.memory_kind:=kind;
 new.provenance:=jsonb_build_object('policyVersion','memory-boundary-v1','kind',kind,
   'origin',case when new.source_event_id is null then 'user' else 'learning_event' end,
   'sourceEventId',new.source_event_id,'subjectId',new.subject_id);
 return new;
end $$;
create trigger stable_memory_entry before insert or update on public.memory_entries for each row execute function public.guard_stable_memory();
-- Rejection of old queued state must remain possible; only approval/new content is guarded.
create trigger stable_memory_request before insert or update of content,subject_id,source_event_id on public.memory_write_requests for each row execute function public.guard_stable_memory();
create function public.invalidate_deleted_memory_snapshots() returns trigger language plpgsql set search_path=public as $$
begin
 delete from memory_snapshots where user_id=old.user_id;
 return old;
end $$;
create trigger removed_memory_snapshots after delete on public.memory_entries for each row execute function public.invalidate_deleted_memory_snapshots();
revoke insert,update,delete on public.memory_entries,public.memory_write_requests,public.memory_snapshots from public,authenticated,anon;

create function public.guard_profile_exam_state() returns trigger language plpgsql set search_path=public as $$
begin
 if new.exam_date is not null and (tg_op='INSERT' or new.exam_date is distinct from old.exam_date) then
   raise exception 'Use subject exam goals' using errcode='22023'; end if;
 return new;
end $$;
create trigger profile_exam_state before insert or update on public.learner_profiles for each row execute function public.guard_profile_exam_state();

create function public.freeze_teaching_memory(p_user uuid,p_session uuid,p_subject uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare snap memory_snapshots; profile learner_profiles; a text; u text; refs jsonb;
begin
 if p_subject is not null and not exists(select 1 from subjects where id=p_subject and user_id=p_user) then
   raise exception 'Subject unavailable' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_user::text||p_session::text,0));
 select * into profile from learner_profiles where user_id=p_user;
 select * into snap from memory_snapshots where user_id=p_user and session_id=p_session;
 if found and snap.subject_id is distinct from p_subject then raise exception 'Session subject conflict' using errcode='40001'; end if;
 if profile.memory_enabled=false or (snap.id is not null and snap.policy_version is distinct from 'memory-boundary-v1') then
   return jsonb_build_object('session_id',p_session,'subject_id',p_subject,'assistant_memory','','user_profile','',
     'teaching_profile','{}'::jsonb,'manifest','[]'::jsonb,'policy_version','memory-boundary-v1','suppressed',true);
 end if;
 if snap.id is not null then return to_jsonb(snap); end if;
 select coalesce(string_agg(content,E'\n§\n' order by importance desc,id) filter(where target='assistant_memory'),''),
   coalesce(string_agg(content,E'\n§\n' order by importance desc,id) filter(where target='user_profile'),''),
   coalesce(jsonb_agg(jsonb_build_object('entryId',id,'kind',memory_kind,'provenance',provenance) order by importance desc,id),'[]'::jsonb)
 into a,u,refs from memory_entries where user_id=p_user and (subject_id is null or subject_id=p_subject)
   and memory_kind<>'legacy' and memory_kind=classify_stable_memory(content);
 insert into memory_snapshots(user_id,subject_id,session_id,assistant_memory,user_profile,assistant_chars,user_chars,policy_version,teaching_profile,manifest)
 values(p_user,p_subject,p_session,a,u,length(a),length(u),'memory-boundary-v1',
   jsonb_build_object('preferredRole',case when profile.preferred_role in ('auto','beginner','crash_course','socratic','examiner','performance_coach','academic','sprint_planner') then profile.preferred_role else 'auto' end,
     'responseStyle',case when profile.response_style in ('concise','balanced','detailed') then profile.response_style else 'balanced' end),refs) returning * into snap;
 return to_jsonb(snap);
end $$;
revoke all on function public.freeze_teaching_memory(uuid,uuid,uuid) from public,anon,authenticated;
grant execute on function public.freeze_teaching_memory(uuid,uuid,uuid) to service_role;

create function public.read_study_behavior(p_user uuid,p_subject uuid) returns jsonb
language plpgsql stable security definer set search_path=public as $$
begin
 if not exists(select 1 from subjects where id=p_subject and user_id=p_user) then raise exception 'Subject unavailable' using errcode='42501'; end if;
 return (select jsonb_build_object('version','study-behavior-v1','windowDays',30,'asOf',now(),
   'source','study_sessions','sessionCount',count(*),'completedCount',count(*) filter(where status='completed'),
   'cancelledCount',count(*) filter(where status='cancelled'),
   'completedBudgetMinutes',coalesce(sum(minutes) filter(where status='completed'),0),
   'note','Budget minutes are planned durations, not measured study time')
   from study_sessions where user_id=p_user and subject_id=p_subject and created_at>=now()-interval '30 days');
end $$;
revoke all on function public.read_study_behavior(uuid,uuid) from public,anon,authenticated;
grant execute on function public.read_study_behavior(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
