begin;
alter table learning_job_outbox add column manual_retries integer not null default 0;
alter table study_plans add column replan_dirty_since timestamptz;
create function public.track_replan_dirty_since() returns trigger language plpgsql set search_path=public as $$
begin
 if not new.replan_required then new.replan_dirty_since:=null;
 elsif tg_op='INSERT' then new.replan_dirty_since:=clock_timestamp();
 elsif not old.replan_required or old.replan_dirty_since is null then new.replan_dirty_since:=clock_timestamp();
 else new.replan_dirty_since:=old.replan_dirty_since;end if;
 return new;
end $$;
create trigger replan_dirty_window before insert or update of replan_required on study_plans for each row execute function track_replan_dirty_since();
create table public.learning_domain_events (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,schema_version integer not null default 1,
 event_type text not null check(event_type in ('material.indexed','exam.completed','mastery.changed','flashcard.reviewed','exam.updated','task.missed')),
 source_table text not null,source_id uuid not null,revision text not null,payload jsonb not null default '{}',
 occurred_at timestamptz not null default clock_timestamp(),consumed_at timestamptz,
 unique(event_type,source_table,source_id,revision),foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create table public.learning_projection_versions (
 user_id uuid not null,subject_id uuid not null,version bigint not null default 1,last_event_id uuid not null,
 updated_at timestamptz not null default now(),primary key(user_id,subject_id),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create unique index projection_job_once on learning_job_outbox(source_id) where kind='projection_refresh';
do $$ declare tab text;begin
 foreach tab in array array['learning_domain_events','learning_projection_versions'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('create policy "Read own %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
 execute format('revoke all on public.%I from public,anon,authenticated',tab);
 execute format('grant select on public.%I to authenticated',tab);
 execute format('grant all on public.%I to service_role',tab);
 end loop;
end $$;

create function public.queue_domain_event() returns trigger language plpgsql security definer set search_path=public as $$
begin
 insert into learning_job_outbox(user_id,subject_id,kind,day,source_id,available_at)
 values(new.user_id,new.subject_id,'projection_refresh',(new.occurred_at at time zone 'Asia/Shanghai')::date,new.id,now()+interval '30 seconds') on conflict do nothing;
 return null;
end $$;
create trigger domain_event_outbox after insert on learning_domain_events for each row execute function queue_domain_event();

create function public.capture_learning_domain_event() returns trigger language plpgsql security definer set search_path=public as $$
declare item jsonb; prior jsonb; kind text; source uuid; rev text; uid uuid; sid uuid;
begin
 item:=case when tg_op='DELETE' then to_jsonb(old) else to_jsonb(new) end;
 prior:=case when tg_op='INSERT' then '{}'::jsonb else to_jsonb(old) end;
 uid:=(item->>'user_id')::uuid;sid:=(item->>'subject_id')::uuid;
 if not exists(select 1 from subjects where id=sid and user_id=uid) then return null;end if;
 if tg_op='UPDATE' and (item-'updated_at')=(prior-'updated_at') then return null;end if;
 source:=(item->>'id')::uuid;
 case tg_table_name
 when 'materials' then
  if item->>'status'<>'ready' or prior->>'status'='ready' then return null;end if;kind:='material.indexed';
 when 'exam_attempts' then
  if item->>'status'<>'graded' or prior->>'status'='graded' then return null;end if;kind:='exam.completed';
 when 'knowledge_mastery' then kind:='mastery.changed';
 when 'flashcard_review_logs' then kind:='flashcard.reviewed';
 when 'exam_events' then kind:='exam.updated';
 when 'exam_topic_map' then kind:='exam.updated';source:=(item->>'exam_event_id')::uuid;
 when 'review_tasks' then
  if item->>'status'<>'overdue' or prior->>'status'='overdue' then return null;end if;kind:='task.missed';
 else return null;
 end case;
 rev:=case when kind='task.missed' then item->>'scheduled_date' when tg_table_name='flashcard_review_logs' then source::text
  else txid_current()::text||':'||tg_op||':'||md5(item::text) end;
 insert into learning_domain_events(user_id,subject_id,event_type,source_table,source_id,revision,payload)
 values(uid,sid,kind,tg_table_name,source,rev,jsonb_strip_nulls(jsonb_build_object('knowledgeKey',item->>'knowledge_key','scheduledDate',item->>'scheduled_date')))
 on conflict do nothing;
 return null;
end $$;
do $$ declare tab text;begin
 foreach tab in array array['materials','exam_attempts','knowledge_mastery','exam_events','review_tasks'] loop
 execute format('create trigger domain_learning_event after insert or update on public.%I for each row execute function capture_learning_domain_event()',tab);
 end loop;
end $$;
create trigger domain_card_event after insert on flashcard_review_logs for each row execute function capture_learning_domain_event();
create trigger domain_exam_scope_event after insert or update or delete on exam_topic_map for each row execute function capture_learning_domain_event();

create function public.enqueue_learning_due_events() returns integer language plpgsql security definer set search_path=public as $$
declare inserted integer;
begin
 insert into learning_domain_events(user_id,subject_id,event_type,source_table,source_id,revision,payload)
 select t.user_id,t.subject_id,'task.missed','review_tasks',t.id,t.scheduled_date::text,jsonb_build_object('scheduledDate',t.scheduled_date)
 from review_tasks t join study_plans p on p.id=t.plan_id and p.user_id=t.user_id and p.status='active'
 where t.status='pending' and t.source='system' and not t.locked and t.scheduled_date<(now() at time zone 'Asia/Shanghai')::date
 and not exists(select 1 from learning_domain_events e where e.event_type='task.missed' and e.source_table='review_tasks' and e.source_id=t.id and e.revision=t.scheduled_date::text)
 order by t.scheduled_date,t.id limit 100 on conflict do nothing;
 get diagnostics inserted=row_count;return inserted;
end $$;

create function public.consume_learning_projection_job(p_job uuid,p_token uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare job learning_job_outbox;event learning_domain_events;epoch bigint;
begin
 select * into job from learning_job_outbox where id=p_job for update;
 if not found or job.kind<>'projection_refresh' then raise exception 'Job unavailable' using errcode='42501';end if;
 if job.status='succeeded' then return jsonb_build_object('consumed',false);end if;
 if job.status<>'running' or job.claim_token is distinct from p_token or job.lease_until<=now() then raise exception 'Lease changed' using errcode='40001';end if;
 select * into event from learning_domain_events where id=job.source_id and user_id=job.user_id and subject_id=job.subject_id for update;
 if not found then raise exception 'Event unavailable' using errcode='22023';end if;
 if event.consumed_at is null then
  insert into learning_projection_versions(user_id,subject_id,last_event_id) values(job.user_id,job.subject_id,event.id)
  on conflict(user_id,subject_id) do update set version=learning_projection_versions.version+1,last_event_id=excluded.last_event_id,updated_at=now() returning version into epoch;
  update study_plans set replan_required=true,replan_reason='learning domain event',version=version+1
   where user_id=job.user_id and subject_id=job.subject_id and status='active' and not replan_required
   and updated_at<event.occurred_at and strategy->>'algorithmVersion'='exam-state-scheduler-v3';
  update learning_domain_events set consumed_at=now() where id=event.id;
 end if;
 perform finish_learning_job(p_job,p_token,null,event.id);
 return jsonb_build_object('consumed',true,'projectionVersion',epoch);
end $$;

create function public.retry_learning_job(p_user uuid,p_job uuid) returns jsonb language plpgsql security definer set search_path=public as $$
declare job learning_job_outbox;
begin
 select * into job from learning_job_outbox where id=p_job and user_id=p_user for update;
 if not found then raise exception 'Job unavailable' using errcode='42501';end if;
 if job.status<>'dead' or job.manual_retries>=3 then raise exception 'Retry unavailable' using errcode='40001';end if;
 if job.kind='daily_review' and (job.day<>(now() at time zone 'Asia/Shanghai')::date or not exists(select 1 from daily_review_schedules where user_id=job.user_id and subject_id=job.subject_id and enabled)) then
  raise exception 'Daily review expired or disabled' using errcode='22023';end if;
 update learning_job_outbox set status='queued',attempts=0,manual_retries=manual_retries+1,available_at=now(),claim_token=null,lease_until=null,error_code=null where id=p_job returning * into job;
 return to_jsonb(job)-'user_id'-'claim_token';
end $$;

-- A quiet 30-second window coalesces burst events; a 2-minute cap avoids starvation.
create or replace function public.study_plan_replan_candidates() returns setof public.study_plans language sql set search_path=public as $$
 select p.* from study_plans p where p.status='active' and p.exam_date>(now() at time zone 'Asia/Shanghai')::date
 and p.strategy->>'algorithmVersion'='exam-state-scheduler-v3' and p.strategy->>'autoReplan'='true'
 and (p.replan_required or exists(select 1 from review_tasks t where t.plan_id=p.id and t.user_id=p.user_id and t.source='system' and not t.locked and t.status='pending' and t.scheduled_date<(now() at time zone 'Asia/Shanghai')::date))
 and (p.replan_dirty_since<=now()-interval '2 minutes' or not exists(select 1 from learning_job_outbox j where j.user_id=p.user_id and j.subject_id=p.subject_id and j.kind='projection_refresh'
  and j.status in ('queued','running') and j.available_at>now()))
 order by p.updated_at limit 20
$$;
revoke all on function public.enqueue_learning_due_events(),public.consume_learning_projection_job(uuid,uuid),public.retry_learning_job(uuid,uuid) from public,anon,authenticated;
grant execute on function public.enqueue_learning_due_events(),public.consume_learning_projection_job(uuid,uuid),public.retry_learning_job(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
