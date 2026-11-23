begin;
-- Payloads expire; minimal pseudonymous dedupe fingerprints survive until
-- subject/account deletion so a retried publisher cannot resurrect old samples.
create table public.retention_receipts (
 user_id uuid not null,subject_id uuid not null,family text not null,fingerprint bytea not null,
 purged_at timestamptz not null default now(),primary key(family,fingerprint),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
alter table retention_receipts enable row level security;
revoke all on retention_receipts from public,anon,authenticated;
grant select,delete on retention_receipts to service_role;
create index retention_receipts_owner on retention_receipts(user_id,subject_id);

create function public.retention_fingerprint(family text,item jsonb) returns bytea
language sql immutable set search_path=public as $$
 select sha256(convert_to(jsonb_build_array(family,item->>'user_id',
 case when family in ('product_events','learning_domain_events') then
  jsonb_build_array(item->>'event_type',item->>'source_table',item->>'source_id',item->>'revision')
 when family='learning_metric_cohorts' then jsonb_build_array(item->>'kind',item->>'source_id',item->>'revision')
 else jsonb_build_array(item->>'id') end)::text,'UTF8'))
$$;
create function public.reject_retained_replay() returns trigger
language plpgsql security definer set search_path=public as $$
begin
 if exists(select 1 from retention_receipts where family=tg_table_name
  and fingerprint=retention_fingerprint(tg_table_name,to_jsonb(new))) then return null;end if;
 return new;
end $$;
do $$ declare tab text;begin
 foreach tab in array array['recommendation_audits','product_events','learning_metric_cohorts',
 'mastery_prediction_samples','mastery_prediction_coverage','learning_domain_events'] loop
 execute format('create trigger retention_replay before insert on public.%I for each row execute function reject_retained_replay()',tab);
 end loop;
end $$;

-- Every family has a bounded batch. The whole call is one transaction.
-- The user scope is for isolated administration/testing, never a public API.
create function public.prune_retained_data(p_audit_days integer default 180,p_metric_days integer default 365,
 p_event_days integer default 180,p_limit integer default 200,p_dry_run boolean default true,p_user uuid default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare tab text;time_column text;cutoff timestamptz;predicate text;row_data jsonb;n integer;counts jsonb:='{}';
begin
 if p_audit_days is null or p_metric_days is null or p_event_days is null or p_limit is null or p_dry_run is null
 or p_audit_days not between 120 and 3650 or p_metric_days not between 120 and 3650
 or p_event_days not between 120 and 3650 or p_limit not between 1 and 1000 then
 raise exception 'Invalid retention policy' using errcode='22023';end if;
 foreach tab in array array['product_events','recommendation_audits','learning_metric_cohorts',
 'mastery_prediction_samples','mastery_prediction_coverage','learning_domain_events'] loop
 time_column:=case when tab='learning_metric_cohorts' then 'deadline'
  when tab in ('mastery_prediction_samples','mastery_prediction_coverage') then 'released_at'
  when tab='learning_domain_events' then 'occurred_at' else 'created_at' end;
 cutoff:=now()-make_interval(days=>case when tab in ('product_events','recommendation_audits') then p_audit_days
  when tab='learning_domain_events' then p_event_days else p_metric_days end);
 predicate:=case when tab='learning_domain_events' then
  ' and t.consumed_at is not null and not exists(select 1 from learning_job_outbox j where j.kind=''projection_refresh'' and j.source_id=t.id and j.status<>''succeeded'')'
  else '' end;
 n:=0;
 for row_data in execute format('select to_jsonb(t) from public.%I t where %I<$1 and ($2 is null or user_id=$2)%s order by %I,id limit $3 for update skip locked',
  tab,time_column,predicate,time_column) using cutoff,p_user,p_limit loop
  n:=n+1;
  if not p_dry_run then
   insert into retention_receipts(user_id,subject_id,family,fingerprint)
    values((row_data->>'user_id')::uuid,(row_data->>'subject_id')::uuid,tab,retention_fingerprint(tab,row_data)) on conflict do nothing;
   execute format('delete from public.%I where id=$1',tab) using (row_data->>'id')::uuid;
  end if;
 end loop;
 counts:=counts||jsonb_build_object(tab,n);
 end loop;
 return jsonb_build_object('dryRun',p_dry_run,'counts',counts,'batchLimitPerFamily',p_limit,'policy',
  jsonb_build_object('auditDays',p_audit_days,'metricDays',p_metric_days,'eventDays',p_event_days),
  'moreMayRemain',exists(select 1 from jsonb_each_text(counts) e where e.value::integer=p_limit));
end $$;

alter table material_assets add column cleanup_token uuid;
alter table material_assets add column cleanup_lease_until timestamptz;
alter table material_assets add column cleanup_attempts integer not null default 0;
alter table material_assets add column cleanup_retry_at timestamptz;
alter table material_assets add column cleanup_error text;
alter table material_assets add column cleanup_expected_hash text;
alter table material_assets add column cleanup_expected_expiry timestamptz;
create index material_assets_retention_due on material_assets(expires_at,cleanup_retry_at) where expires_at is not null;
create index domain_event_retention_due on learning_domain_events(occurred_at,id) where consumed_at is not null;
create index cohort_retention_due on learning_metric_cohorts(deadline,id);
create index audit_retention_due on recommendation_audits(created_at,id);
create index product_retention_due on product_events(created_at,id);
create index sample_retention_due on mastery_prediction_samples(released_at,id);
create index coverage_retention_due on mastery_prediction_coverage(released_at,id);

create function public.claim_expired_assets(p_limit integer default 50,p_user uuid default null) returns jsonb
language plpgsql security definer set search_path=public as $$
declare result jsonb;
begin
 if p_limit is null or p_limit not between 1 and 100 then raise exception 'Invalid batch size' using errcode='22023';end if;
 with due as (
  select a.id from material_assets a join materials m on m.id=a.material_id and m.user_id=a.user_id and m.subject_id=a.subject_id
  where a.expires_at<=now() and (p_user is null or a.user_id=p_user)
  and m.status in ('ready','failed')
  and not exists(select 1 from processing_tasks t where t.material_id=a.material_id and t.status in ('queued','running'))
  and not exists(select 1 from audio_segments s where s.material_id=a.material_id and s.status in ('queued','transcribing'))
  and coalesce(a.cleanup_lease_until,'-infinity'::timestamptz)<=now()
  and coalesce(a.cleanup_retry_at,'-infinity'::timestamptz)<=now()
  order by a.expires_at,a.id limit p_limit for update of a skip locked
 ), claimed as (
  update material_assets a set cleanup_token=gen_random_uuid(),cleanup_lease_until=now()+interval '5 minutes',
   cleanup_attempts=cleanup_attempts+1,cleanup_error=null,cleanup_expected_hash=a.sha256,
   cleanup_expected_expiry=a.expires_at from due where a.id=due.id returning a.*)
 select coalesce(jsonb_agg(to_jsonb(c)),'[]') into result from claimed c;
 return result;
end $$;

create function public.finish_asset_cleanup(p_asset uuid,p_token uuid,p_error text default null) returns boolean
language plpgsql security definer set search_path=public as $$
declare item material_assets;
begin
 select * into item from material_assets where id=p_asset and cleanup_token=p_token
  and cleanup_lease_until>now() for update;
 if not found then return false;end if;
 if p_error is null and (item.sha256 is distinct from item.cleanup_expected_hash
   or item.expires_at is distinct from item.cleanup_expected_expiry or item.expires_at>now()) then
  return false;
 elsif p_error is null then
  delete from material_assets where id=p_asset;
 else
  update material_assets set cleanup_token=null,cleanup_lease_until=null,cleanup_error=left(p_error,80),
   cleanup_retry_at=now()+make_interval(secs=>least(86400,60*power(2,least(cleanup_attempts,11)))::integer)
   where id=p_asset;
 end if;
 return true;
end $$;
-- Validate manifest and eligibility immediately before the external operation.
create function public.check_asset_cleanup(p_asset uuid,p_token uuid) returns boolean
language sql stable security definer set search_path=public as $$
 select exists(select 1 from material_assets a join materials m on m.id=a.material_id and m.user_id=a.user_id and m.subject_id=a.subject_id
 where a.id=p_asset and a.cleanup_token=p_token and a.cleanup_lease_until>now() and a.expires_at<=now()
 and a.sha256=a.cleanup_expected_hash and a.expires_at=a.cleanup_expected_expiry
 and m.status in ('ready','failed')
 and not exists(select 1 from processing_tasks t where t.material_id=a.material_id and t.status in ('queued','running'))
 and not exists(select 1 from audio_segments s where s.material_id=a.material_id and s.status in ('queued','transcribing')))
$$;
create function public.preview_expired_assets(p_limit integer default 50,p_user uuid default null) returns integer
language plpgsql stable security definer set search_path=public as $$
declare n integer;
begin
 if p_limit is null or p_limit not between 1 and 100 then raise exception 'Invalid batch size' using errcode='22023';end if;
 select count(*) into n from (select a.id from material_assets a join materials m on m.id=a.material_id and m.user_id=a.user_id and m.subject_id=a.subject_id
 where a.expires_at<=now() and (p_user is null or a.user_id=p_user) and m.status in ('ready','failed')
 and not exists(select 1 from processing_tasks t where t.material_id=a.material_id and t.status in ('queued','running'))
 and not exists(select 1 from audio_segments s where s.material_id=a.material_id and s.status in ('queued','transcribing'))
 and coalesce(a.cleanup_lease_until,'-infinity'::timestamptz)<=now()
 and coalesce(a.cleanup_retry_at,'-infinity'::timestamptz)<=now() limit p_limit) q;
 return n;
end $$;
-- Retain the legacy completed-step guard even after its full event expires.
create or replace function public.capture_learning_cohort() returns trigger language plpgsql security definer set search_path=public as $$
declare prior jsonb;ver text;start_time timestamptz;session study_sessions;score double precision;
begin
 prior:=case when tg_op='INSERT' then '{}'::jsonb else to_jsonb(old) end;
 case tg_table_name
 when 'study_sessions' then
  if new.status='active' and prior->>'status' is distinct from 'active' then
   start_time:=clock_timestamp();
   insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline)
   values(new.user_id,new.subject_id,'guided_session',new.id,'1',coalesce(new.context->>'algorithmVersion','legacy-unversioned'),start_time,start_time+interval '7 days') on conflict do nothing;
  elsif new.status='completed' and prior->>'status' is distinct from 'completed' then
   update learning_metric_cohorts set completed_at=clock_timestamp() where user_id=new.user_id and kind='guided_session' and source_id=new.id and completed_at is null;
  end if;
 when 'review_tasks' then
  if tg_op='INSERT' then
   select coalesce(strategy->>'algorithmVersion','legacy-unversioned') into ver from study_plans where id=new.plan_id and user_id=new.user_id;
   start_time:=greatest(clock_timestamp(),new.scheduled_date::timestamp at time zone 'Asia/Shanghai');
   insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline,context)
   values(new.user_id,new.subject_id,'plan_task',new.id,'1',coalesce(ver,'manual-task-v1'),start_time,start_time+interval '7 days',
   jsonb_build_object('planId',new.plan_id,'scheduledDate',new.scheduled_date,'source',new.source)) on conflict do nothing;
  end if;
  if new.status='completed' then
   update learning_metric_cohorts set completed_at=clock_timestamp() where user_id=new.user_id and kind='plan_task' and source_id=new.id and completed_at is null;
  end if;
 when 'flashcard_review_state' then
  if tg_op='UPDATE' and new.version=old.version and new.next_review=old.next_review then return null;end if;
  start_time:=greatest(clock_timestamp(),new.next_review);
  insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline,context)
  values(new.user_id,new.subject_id,'due_flashcard',new.artifact_id,new.card_id||':'||new.content_version||':'||new.version,
  'card-scheduler-v1',start_time,start_time+interval '7 days',jsonb_build_object('cardId',new.card_id,'contentVersion',new.content_version,'stateVersion',new.version,'dueAt',new.next_review)) on conflict do nothing;
 when 'flashcard_review_logs' then
  update learning_metric_cohorts set completed_at=clock_timestamp()
  where user_id=new.user_id and kind='due_flashcard' and source_id=new.artifact_id
  and context->>'cardId'=new.card_id and (context->>'contentVersion')::integer=new.content_version
  and (context->>'stateVersion')::integer=new.expected_version and completed_at is null;
 when 'study_session_steps' then
  if new.kind<>'quiz' or new.status<>'completed' or prior->>'status'='completed' then return null;end if;
  -- save_guided_session rebuilds steps. Do not turn a pre-migration completion into a new failure.
  if exists(select 1 from product_events where user_id=new.user_id and source_id=new.id and event_type='step.completed')
  or exists(select 1 from retention_receipts where family='product_events' and fingerprint=retention_fingerprint('product_events',
   jsonb_build_object('user_id',new.user_id,'event_type','step.completed','source_table','study_session_steps','source_id',new.id,'revision','1')))
  then return null;end if;
  score:=(new.output->>'scoreRatio')::double precision;
  select * into session from study_sessions where id=new.session_id and user_id=new.user_id;
  if session.context->>'algorithmVersion' is null then return null;end if;
  if score<.8 then
   start_time:=clock_timestamp();
   insert into learning_metric_cohorts(user_id,subject_id,kind,source_id,revision,algorithm_version,starts_at,deadline,context)
   values(new.user_id,new.subject_id,'quiz_remediation',new.session_id,'1',coalesce(session.context->>'algorithmVersion','legacy-unversioned'),start_time,start_time+interval '7 days',
   jsonb_build_object('failedStepId',new.id,'sequenceIndex',new.sequence_index,'scoreRatio',score)) on conflict do nothing;
  elsif score>=.8 then
   update learning_metric_cohorts set completed_at=clock_timestamp() where user_id=new.user_id and source_id=new.session_id and kind='quiz_remediation'
   and (context->>'sequenceIndex')::integer<new.sequence_index and completed_at is null;
  end if;
 when 'grading_results' then perform capture_released_mastery_samples(new.attempt_id);
 when 'exam_attempts' then
  if new.status='graded' and prior->>'status' is distinct from 'graded' then perform capture_released_mastery_samples(new.id);end if;
 end case;
 return null;
end $$;
revoke all on function retention_fingerprint(text,jsonb),reject_retained_replay(),prune_retained_data(integer,integer,integer,integer,boolean,uuid),
 claim_expired_assets(integer,uuid),finish_asset_cleanup(uuid,uuid,text),check_asset_cleanup(uuid,uuid),preview_expired_assets(integer,uuid) from public,anon,authenticated;
grant execute on function prune_retained_data(integer,integer,integer,integer,boolean,uuid),claim_expired_assets(integer,uuid),
 finish_asset_cleanup(uuid,uuid,text),check_asset_cleanup(uuid,uuid),preview_expired_assets(integer,uuid) to service_role;
notify pgrst,'reload schema';
commit;
