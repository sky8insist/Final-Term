begin;
create table public.recommendation_audits (
 id uuid primary key,user_id uuid not null references auth.users(id) on delete cascade,
 subject_id uuid not null,knowledge_point_id uuid,algorithm_version text not null,
 snapshot jsonb not null,created_at timestamptz not null default clock_timestamp(),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade,
 foreign key(knowledge_point_id,user_id,subject_id) references knowledge_points(id,user_id,subject_id) on delete cascade
);
create index recommendation_audit_owner on recommendation_audits(user_id,created_at desc);
create table public.product_events (
 id uuid primary key default gen_random_uuid(),user_id uuid not null references auth.users(id) on delete cascade,
 subject_id uuid not null,schema_version integer not null default 1,
 event_type text not null check(event_type in ('recommendation.impression','recommendation.clicked',
 'session.accepted','session.completed','step.completed','mastery.changed','plan.replanned','task.completed','adaptive.stopped','grade.calibrated')),
 source_table text not null,source_id uuid not null,revision text not null,
 algorithm_version text not null,payload jsonb not null default '{}',created_at timestamptz not null default clock_timestamp(),
 unique(event_type,source_table,source_id,revision),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create index product_events_owner on product_events(user_id,event_type,created_at desc);
create index product_events_source on product_events(user_id,source_id,event_type);
create index product_events_attribution on product_events(user_id,(payload->>'recommendationId'),event_type);
create index product_events_recommendation on product_events using gin(payload jsonb_path_ops);
do $$ declare tab text;begin
 foreach tab in array array['recommendation_audits','product_events'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('create policy "Read own %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
 execute format('revoke all on public.%I from public,anon,authenticated,service_role',tab);
 execute format('grant select on public.%I to authenticated',tab);
 execute format('grant select,insert,delete on public.%I to service_role',tab);
 end loop;
end $$;

create function public.record_recommendation_feedback(p_user uuid,p_recommendation uuid,p_event text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare rec recommendation_audits;inserted integer;
begin
 select * into rec from recommendation_audits where id=p_recommendation and user_id=p_user;
 if not found then raise exception 'Unavailable recommendation' using errcode='42501';end if;
 if p_event not in ('impression','clicked') or rec.created_at<clock_timestamp()-interval '7 days' then
 raise exception 'Expired or invalid feedback' using errcode='22023';end if;
 insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,payload)
 values(p_user,rec.subject_id,'recommendation.'||p_event,'recommendation_audits',rec.id,'1',rec.algorithm_version,
 jsonb_build_object('recommendationId',rec.id,'reportedBy','client')) on conflict do nothing;
 get diagnostics inserted=row_count;
 return jsonb_build_object('recorded',inserted=1);
end $$;

-- Validate attribution in the same transaction that creates the canonical session.
create function public.validate_session_recommendation() returns trigger language plpgsql security definer set search_path=public as $$
begin
 if new.context->>'recommendationId' is not null and not exists(
 select 1 from recommendation_audits r where r.id=(new.context->>'recommendationId')::uuid
 and r.user_id=new.user_id and r.subject_id=new.subject_id and r.knowledge_point_id=new.knowledge_point_id
 and r.created_at>=clock_timestamp()-interval '7 days') then
 raise exception 'Invalid recommendation attribution' using errcode='22023';end if;
 return new;
end $$;
create trigger validate_session_recommendation before insert on study_sessions for each row execute function validate_session_recommendation();

-- Match grading_results release rules; an audit must not leak an unreleased formal grade.
create function public.capture_released_calibration(p_attempt uuid) returns void
language sql security definer set search_path=public as $$
 insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,payload)
 select a.user_id,a.subject_id,'grade.calibrated','grading_results',g.id,'1','learner-confidence-calibration-v1',
 jsonb_build_object('attemptId',a.id,'confidence',g.learner_confidence,'correct',g.is_correct,
 'brier',power(g.learner_confidence-case when g.is_correct then 1 else 0 end,2))
 from grading_results g join exam_attempts a on a.id=g.attempt_id and a.user_id=g.user_id join exams e on e.id=a.exam_id
 where a.id=p_attempt and (a.status='graded' or e.assessment_mode='adaptive')
 and g.learner_confidence is not null and g.is_correct is not null on conflict do nothing;
$$;

create function public.capture_product_event() returns trigger language plpgsql security definer set search_path=public as $$
declare item jsonb:=to_jsonb(new);prior jsonb;kind text;ver text;rev text:='1';body jsonb:='{}';session study_sessions;
begin
 prior:=case when tg_op='INSERT' then '{}'::jsonb else to_jsonb(old) end;
 case tg_table_name
 when 'study_sessions' then
  if item->>'status'=prior->>'status' then return null;end if;
  if new.status='active' then kind:='session.accepted';
  elsif new.status='completed' then kind:='session.completed';else return null;end if;
  ver:=coalesce(new.context->>'algorithmVersion','legacy-unversioned');
  body:=jsonb_build_object('recommendationId',new.context->>'recommendationId','knowledgePointId',new.knowledge_point_id);
  if new.status='completed' then body:=body||jsonb_build_object('before',new.summary->'before','after',new.summary->'after',
   'skippedSteps',new.summary->'skippedSteps','extraMinutes',new.summary->'extraMinutes');end if;
 when 'study_session_steps' then
  if new.status<>'completed' or prior->>'status'='completed' then return null;end if;
  select * into session from study_sessions where id=new.session_id;
  kind:='step.completed';ver:=coalesce(session.context->>'algorithmVersion','legacy-unversioned');
  body:=jsonb_build_object('sessionId',new.session_id,'recommendationId',session.context->>'recommendationId','kind',new.kind,
   'scoreRatio',new.output->'scoreRatio','attemptId',new.output->'attemptId');
 when 'knowledge_mastery' then
  if tg_op='UPDATE' and new.mastery is not distinct from old.mastery and new.confidence is not distinct from old.confidence
   and new.attempts=old.attempts then return null;end if;
  kind:='mastery.changed';ver:=coalesce(new.metadata->'lastEvidence'->>'algorithmVersion','legacy-unversioned');rev:=gen_random_uuid()::text;
  body:=jsonb_build_object('knowledgeKey',new.knowledge_key,'before',prior->'mastery','after',new.mastery,
   'deltaPoints',case when tg_op='UPDATE' then 100*(new.mastery-old.mastery) else null end,
   'beforeConfidence',prior->'confidence','afterConfidence',new.confidence,'attempts',new.attempts);
 when 'study_plan_events' then
  if new.event_type<>'replanned' then return null;end if;
  kind:='plan.replanned';select coalesce(strategy->>'algorithmVersion','legacy-unversioned') into ver from study_plans where id=new.plan_id;
  body:=jsonb_build_object('planId',new.plan_id,'version',new.details->'version','taskCount',new.details->'taskCount');
 when 'review_tasks' then
  if new.status<>'completed' or prior->>'status'='completed' then return null;end if;
  kind:='task.completed';ver:='task-completion-v1';
  body:=jsonb_build_object('planId',new.plan_id,'scheduledDate',new.scheduled_date,'source',new.source);
 when 'exam_attempts' then
  if new.status='graded' and prior->>'status' is distinct from 'graded' then perform capture_released_calibration(new.id);end if;
  if not coalesce((new.adaptive_state->>'paused')::boolean,false) or coalesce((prior->'adaptive_state'->>'paused')::boolean,false) then return null;end if;
  kind:='adaptive.stopped';ver:='adaptive-recent-window-035';rev:=coalesce(new.adaptive_state->>'resumeCount','0');
  body:=jsonb_build_object('reason',new.adaptive_state->'reason','count',new.adaptive_state->'count','resumeCount',rev);
 when 'grading_results' then
  perform capture_released_calibration(new.attempt_id);return null;
 else return null;
 end case;
 insert into product_events(user_id,subject_id,event_type,source_table,source_id,revision,algorithm_version,payload)
 values((item->>'user_id')::uuid,(item->>'subject_id')::uuid,kind,tg_table_name,(item->>'id')::uuid,rev,ver,jsonb_strip_nulls(body))
 on conflict do nothing;
 return null;
end $$;
do $$ declare tab text;begin
 foreach tab in array array['study_sessions','study_session_steps','knowledge_mastery','review_tasks','exam_attempts'] loop
 execute format('create trigger product_audit after insert or update on public.%I for each row execute function capture_product_event()',tab);
 end loop;
 foreach tab in array array['study_plan_events','grading_results'] loop
 execute format('create trigger product_audit after insert on public.%I for each row execute function capture_product_event()',tab);
 end loop;
end $$;

create function public.product_quality_metrics(p_user uuid,p_days integer default 7) returns jsonb
language plpgsql security definer set search_path=public as $$
declare result jsonb;cutoff timestamptz:=clock_timestamp()-make_interval(days=>p_days);
begin
 if p_days not between 1 and 90 then raise exception 'Invalid window' using errcode='22023';end if;
 with cohort as (
 select r.id,r.algorithm_version,
 exists(select 1 from product_events e where e.user_id=p_user and e.source_id=r.id and e.event_type='recommendation.impression') exposed,
 exists(select 1 from product_events e where e.user_id=p_user and e.source_id=r.id and e.event_type='recommendation.clicked') clicked,
 exists(select 1 from product_events e where e.user_id=p_user and e.event_type='session.accepted' and e.payload->>'recommendationId'=r.id::text) accepted,
 exists(select 1 from product_events e where e.user_id=p_user and e.event_type='session.completed' and e.payload->>'recommendationId'=r.id::text) completed
 from recommendation_audits r where r.user_id=p_user and r.created_at>=cutoff
 ), versions as (
 select algorithm_version,count(*) delivered,count(*) filter(where exposed) impressions,
 count(*) filter(where clicked) clicks,count(*) filter(where exposed and clicked) exposed_clicks,
 count(*) filter(where exposed and accepted) accepted,count(*) filter(where exposed and completed) completed
 from cohort group by algorithm_version
 ), counts as (
 select event_type,count(*) n from product_events where user_id=p_user and created_at>=cutoff group by event_type
 ), gains as (
 select 100*((payload->'after'->>'masteryScore')::numeric-(payload->'before'->>'masteryScore')::numeric) delta
 from product_events where user_id=p_user and created_at>=cutoff and event_type='session.completed'
 and (payload->'before'->>'assessmentCount')::integer>0 and (payload->'after'->>'assessmentCount')::integer>0
 )
 select jsonb_build_object('schemaVersion',1,'since',cutoff,'asOf',clock_timestamp(),
 'recommendationCohorts',coalesce((select jsonb_agg(jsonb_build_object('algorithmVersion',algorithm_version,
 'delivered',delivered,'impressions',impressions,'clicks',clicks,'exposedClicks',exposed_clicks,
 'accepted',accepted,'completed',completed,'clickThroughRate',exposed_clicks::numeric/nullif(impressions,0),
 'acceptanceRate',accepted::numeric/nullif(impressions,0),'completionRate',completed::numeric/nullif(accepted,0))) from versions),'[]'),
 'eventCounts',coalesce((select jsonb_object_agg(event_type,n) from counts),'{}'),
 'sessionMasteryGain',jsonb_build_object('sampleCount',(select count(*) from gains),'meanDeltaPoints',(select avg(delta) from gains)),
 'learnerConfidenceCalibration',(select jsonb_build_object('sampleCount',count(*),'brierScore',avg((payload->>'brier')::numeric))
 from product_events where user_id=p_user and created_at>=cutoff and event_type='grade.calibrated'),
 'definitions',jsonb_build_object('recommendations','delivery cohort; unique client-reported exposures/clicks; acceptance requires canonical session active; all outcomes observed up to asOf',
 'masteryGain','completed session before/after with assessment evidence on both sides; observational, not causal',
 'calibration','learner self-confidence versus graded correctness; not mastery calibration',
 'coverage','new events since migration; no historical backfill; task counts and replan counts are not completion rates')) into result;
 return result;
end $$;
revoke all on function public.record_recommendation_feedback(uuid,uuid,text),public.product_quality_metrics(uuid,integer),
 public.capture_product_event(),public.validate_session_recommendation(),public.capture_released_calibration(uuid) from public,anon,authenticated;
grant execute on function public.record_recommendation_feedback(uuid,uuid,text),public.product_quality_metrics(uuid,integer) to service_role;
notify pgrst,'reload schema';
commit;
