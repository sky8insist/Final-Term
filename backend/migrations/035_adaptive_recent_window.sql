begin;
create or replace function public.guard_adaptive_grade() returns trigger language plpgsql set search_path=public as $$
declare attempt public.exam_attempts; mode text; state jsonb; streak integer; total integer; corrects integer;
        mistakes integer; reason text; recent jsonb; recent_correct integer;
begin
    select * into attempt from exam_attempts where id=new.attempt_id for update;
    select assessment_mode into mode from exams where id=attempt.exam_id;
    if mode <> 'adaptive' then return new; end if;
    if exists(select 1 from grading_results where attempt_id=new.attempt_id and question_id=new.question_id) then return new; end if;
    state:=attempt.adaptive_state;
    if coalesce((state->>'paused')::boolean,false) then raise exception 'Quiz paused; complete remediation first' using errcode='23514'; end if;
    streak:=case when new.is_correct then 0 else coalesce((state->>'consecutiveWrong')::integer,0)+1 end;
    total:=coalesce((state->>'count')::integer,0)+1;
    corrects:=coalesce((state->>'correctCount')::integer,0)+case when new.is_correct then 1 else 0 end;
    mistakes:=coalesce((state->>'highConfidenceWrong')::integer,0)+case when not new.is_correct and new.learner_confidence>=0.75 then 1 else 0 end;
    recent:=coalesce(state->'recentResults','[]'::jsonb) || jsonb_build_array(new.is_correct);
    if jsonb_array_length(recent)>5 then recent:=recent-0; end if;
    select count(*) into recent_correct from jsonb_array_elements(recent) r where r='true'::jsonb;
    reason:=case when streak>=3 then '连续三题错误' when mistakes>=2 then '两次高信心错误'
        when jsonb_array_length(recent)>=5 and recent_correct::numeric/jsonb_array_length(recent)<0.4 then '近期正确率低于40%' else null end;
    update exam_attempts set adaptive_state=state || jsonb_build_object('count',total,'correctCount',corrects,
        'consecutiveWrong',streak,'highConfidenceWrong',mistakes,'paused',reason is not null,
        'reason',reason,'recentResults',recent,'pausedAt',case when reason is not null then now() else null end)
        where id=attempt.id;
    return new;
end; $$;
commit;
