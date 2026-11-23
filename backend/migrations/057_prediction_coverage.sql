begin;
create table public.mastery_prediction_coverage (
 id uuid primary key,user_id uuid not null,subject_id uuid not null,
 known_outcome boolean not null,has_prediction boolean not null,
 reason text not null check(reason in ('available','no_response','no_snapshot')),
 released_at timestamptz not null default clock_timestamp(),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create index prediction_coverage_owner on mastery_prediction_coverage(user_id,released_at);
create index recommendation_history_seek on recommendation_audits(user_id,created_at desc,id desc);
create index product_event_history_seek on product_events(user_id,created_at desc,id desc);
alter table mastery_prediction_coverage enable row level security;
create policy "Read own prediction coverage" on mastery_prediction_coverage for select to authenticated using(user_id=auth.uid());
revoke all on mastery_prediction_coverage from public,anon,authenticated,service_role;
grant select on mastery_prediction_coverage to authenticated;
grant select,delete on mastery_prediction_coverage to service_role;

-- Count first publication, not all old grades when another adaptive answer is graded.
create function public.capture_prediction_coverage() returns trigger language plpgsql security definer set search_path=public as $$
declare target_attempt uuid;target_grade uuid;
begin
 if tg_table_name='grading_results' then target_attempt:=new.attempt_id;target_grade:=new.id;
 else
  if new.status<>'graded' or old.status='graded' then return null;end if;
  target_attempt:=new.id;
 end if;
 insert into mastery_prediction_coverage(id,user_id,subject_id,known_outcome,has_prediction,reason)
 select g.id,a.user_id,a.subject_id,g.is_correct is not null,coalesce(r.mastery_prediction ? 'score',false),
 case when r.id is null then 'no_response' when not (r.mastery_prediction ? 'score') then 'no_snapshot' else 'available' end
 from grading_results g join exam_attempts a on a.id=g.attempt_id and a.user_id=g.user_id join exams e on e.id=a.exam_id
 left join exam_responses r on r.attempt_id=a.id and r.question_id=g.question_id and r.user_id=a.user_id
 where a.id=target_attempt and (target_grade is null or g.id=target_grade) and (a.status='graded' or e.assessment_mode='adaptive')
 on conflict do nothing;
 return null;
end $$;
create trigger prediction_coverage_grade after insert on grading_results for each row execute function capture_prediction_coverage();
create trigger prediction_coverage_release after update of status on exam_attempts for each row execute function capture_prediction_coverage();

create function public.prediction_coverage_metrics(p_user uuid,p_days integer default 30) returns jsonb
language plpgsql security definer set search_path=public as $$
declare result jsonb;observed_at timestamptz:=clock_timestamp();
begin
 if p_days is null or p_days not between 1 and 90 then raise exception 'Invalid window' using errcode='22023';end if;
 select jsonb_build_object('schemaVersion',1,'asOf',observed_at,'windowDays',p_days,
 'releasedGrades',count(*),'knownOutcomes',count(*) filter(where known_outcome),
 'predictionSamples',count(*) filter(where known_outcome and has_prediction),
 'missingPrediction',count(*) filter(where known_outcome and not has_prediction),
 'unknownOutcomes',count(*) filter(where not known_outcome),
 'noResponse',count(*) filter(where known_outcome and reason='no_response'),
 'noSnapshot',count(*) filter(where known_outcome and reason='no_snapshot'),
 'coverageRate',count(*) filter(where known_outcome and has_prediction)::numeric/nullif(count(*) filter(where known_outcome),0),
 'definition','prospective first grade release after installation; no historical backfill; denominator=known correctness, numerator=frozen first-response prediction; unknown outcomes excluded; calibration may contain older samples')
 into result from mastery_prediction_coverage where user_id=p_user and released_at>=observed_at-make_interval(days=>p_days);
 return result;
end $$;
revoke all on function capture_prediction_coverage(),prediction_coverage_metrics(uuid,integer) from public,anon,authenticated;
grant execute on function prediction_coverage_metrics(uuid,integer) to service_role;
notify pgrst,'reload schema';
commit;
