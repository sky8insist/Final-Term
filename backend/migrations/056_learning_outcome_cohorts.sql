begin;
create table public.learning_metric_cohorts (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,
 kind text not null check(kind in ('guided_session','plan_task','due_flashcard','quiz_remediation')),
 source_id uuid not null,revision text not null,algorithm_version text not null,
 starts_at timestamptz not null,deadline timestamptz not null,completed_at timestamptz,
 context jsonb not null default '{}',created_at timestamptz not null default clock_timestamp(),
 unique(kind,source_id,revision),check(deadline=starts_at+interval '7 days'),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create index learning_cohort_owner on learning_metric_cohorts(user_id,kind,starts_at);
create index learning_cohort_source on learning_metric_cohorts(user_id,source_id,kind);
alter table exam_responses add column mastery_prediction jsonb not null default '{}';
create table public.mastery_prediction_samples (
 id uuid primary key,user_id uuid not null,subject_id uuid not null,
 attempt_id uuid not null,question_id uuid not null,prediction jsonb not null,actual boolean not null,
 released_at timestamptz not null default clock_timestamp(),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create index mastery_sample_owner on mastery_prediction_samples(user_id,released_at);
do $$ declare tab text;begin
 foreach tab in array array['learning_metric_cohorts','mastery_prediction_samples'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('create policy "Read own %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
 execute format('revoke all on public.%I from public,anon,authenticated,service_role',tab);
 execute format('grant select on public.%I to authenticated',tab);
 execute format('grant select,delete on public.%I to service_role',tab);
 end loop;
end $$;

-- The trusted snapshot is frozen at FIRST response insert, before grading this answer.
-- Re-saving an answer cannot replace it, including legacy rows with an empty snapshot.
create function public.capture_response_prediction() returns trigger language plpgsql security definer set search_path=public as $$
declare m knowledge_mastery;
begin
 if tg_op='UPDATE' then new.mastery_prediction:=old.mastery_prediction;return new;end if;
 select k.* into m from exam_attempts a join questions q on q.id=new.question_id and q.user_id=a.user_id and q.subject_id=a.subject_id
 join knowledge_mastery k on k.user_id=a.user_id and k.subject_id=a.subject_id and k.knowledge_key=q.knowledge_key
 where a.id=new.attempt_id and a.user_id=new.user_id;
 if not found or coalesce((m.metadata->>'assessmentCount')::integer,0)=0 then
 new.mastery_prediction:='{}';return new;end if;
 new.mastery_prediction:=jsonb_build_object('score',m.mastery,'confidence',m.confidence,
 'knowledgeKey',m.knowledge_key,'masteryUpdatedAt',m.updated_at,
 'assessmentCount',m.metadata->'assessmentCount','algorithmVersion',coalesce(m.metadata->'lastEvidence'->>'algorithmVersion','legacy-unversioned'),
 'predictionVersion','first-response-mastery-v1','capturedAt',clock_timestamp());
 return new;
end $$;
create trigger response_prediction before insert or update on exam_responses for each row execute function capture_response_prediction();

create function public.capture_released_mastery_samples(p_attempt uuid) returns void language sql security definer set search_path=public as $$
 insert into mastery_prediction_samples(id,user_id,subject_id,attempt_id,question_id,prediction,actual)
 select g.id,a.user_id,a.subject_id,a.id,g.question_id,r.mastery_prediction,g.is_correct
 from grading_results g join exam_attempts a on a.id=g.attempt_id and a.user_id=g.user_id
 join exams e on e.id=a.exam_id join exam_responses r on r.attempt_id=a.id and r.question_id=g.question_id and r.user_id=a.user_id
 where a.id=p_attempt and (a.status='graded' or e.assessment_mode='adaptive') and g.is_correct is not null
 and r.mastery_prediction ? 'score' on conflict do nothing;
$$;

create function public.capture_learning_cohort() returns trigger language plpgsql security definer set search_path=public as $$
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
  if exists(select 1 from product_events where user_id=new.user_id and source_id=new.id and event_type='step.completed') then return null;end if;
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
do $$ declare tab text;begin
 foreach tab in array array['study_sessions','review_tasks','flashcard_review_state','study_session_steps','exam_attempts'] loop
 execute format('create trigger learning_outcome_cohort after insert or update on public.%I for each row execute function capture_learning_cohort()',tab);
 end loop;
 foreach tab in array array['flashcard_review_logs','grading_results'] loop
 execute format('create trigger learning_outcome_cohort after insert on public.%I for each row execute function capture_learning_cohort()',tab);
 end loop;
end $$;

create function public.learning_outcome_metrics(p_user uuid,p_days integer default 30) returns jsonb
language plpgsql security definer set search_path=public as $$
declare result jsonb;observed_at timestamptz:=clock_timestamp();
begin
 if p_days is null or p_days not between 1 and 90 then raise exception 'Invalid window' using errcode='22023';end if;
 with groups as (
 select kind,algorithm_version,count(*) total,count(*) filter(where deadline<=observed_at) mature,
 count(*) filter(where deadline<=observed_at and completed_at<=deadline) completed,
 count(*) filter(where deadline>observed_at) pending,
 count(*) filter(where deadline<=observed_at and completed_at>deadline) late
 from learning_metric_cohorts where user_id=p_user and starts_at>=observed_at-make_interval(days=>p_days) and starts_at<=observed_at
 group by kind,algorithm_version
 ), samples as (
 select prediction->>'algorithmVersion' ver,(prediction->>'score')::numeric prediction,actual::integer actual,
 least(9,greatest(0,floor((prediction->>'score')::numeric*10))) bucket
 from mastery_prediction_samples where user_id=p_user and released_at>=observed_at-make_interval(days=>p_days)
 ), bins as (
 select ver,bucket,count(*) n,avg(prediction) predicted,avg(actual) observed from samples group by ver,bucket
 ), calibration as (
 select ver,count(*) n,avg(power(prediction-actual,2)) brier from samples group by ver
 )
 select jsonb_build_object('schemaVersion',1,'asOf',observed_at,'windowDays',p_days,'horizonDays',7,
 'cohorts',coalesce((select jsonb_agg(jsonb_build_object('kind',kind,'algorithmVersion',algorithm_version,'total',total,
 'mature',mature,'completedWithinHorizon',completed,'pending',pending,'late',late,'completionRate',completed::numeric/nullif(mature,0)) order by kind,algorithm_version) from groups),'[]'),
 'masteryCalibration',coalesce((select jsonb_agg(jsonb_build_object('algorithmVersion',c.ver,'sampleCount',c.n,'brierScore',c.brier,
 'expectedCalibrationError',(select sum(n*abs(predicted-observed))/sum(n) from bins b where b.ver=c.ver),
 'bins',(select jsonb_agg(jsonb_build_object('lower',bucket/10.0,'upper',(bucket+1)/10.0,'sampleCount',n,'meanPrediction',predicted,'accuracy',observed) order by bucket) from bins b where b.ver=c.ver)) order by c.ver) from calibration c),'[]'),
 'definitions',jsonb_build_object('cohorts','prospective cohorts, fixed seven-day horizon; mature denominator only; source deletions/replans do not remove commitments; privacy deletion cascades',
 'guided_session','first canonical acceptance to completion', 'plan_task','first task schedule, window starts no earlier than insertion; task completion rate, not whole-plan success',
 'due_flashcard','each new schedule/version, including early review; ratings count review completion, not recall success; existing schedules not backfilled',
 'quiz_remediation','first failed Guided quiz per session (<.8), success is a later quiz >=.8',
 'masteryCalibration','first-response mastery score versus released question correctness; score is not a validated probability; no evidence/no snapshot excluded; response saves cannot overwrite prediction',
 'comparison','versions have different populations; descriptive comparisons do not establish causal uplift; calibration window uses grade release time')) into result;
 return result;
end $$;
revoke all on function public.capture_response_prediction(),public.capture_released_mastery_samples(uuid),public.capture_learning_cohort(),public.learning_outcome_metrics(uuid,integer) from public,anon,authenticated;
grant execute on function public.learning_outcome_metrics(uuid,integer) to service_role;
notify pgrst,'reload schema';
commit;
