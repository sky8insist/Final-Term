begin;
alter table public.exams add column assessment_mode text not null default 'formal'
    check(assessment_mode in ('formal','adaptive'));
update public.exams e set assessment_mode='adaptive' from public.exam_blueprints b
    where e.blueprint_id=b.id and b.specification->>'assessmentType'='practice';
alter table public.exam_attempts add column adaptive_state jsonb not null default '{}'::jsonb;
alter table public.exam_responses add column response_seconds double precision check(response_seconds between 0 and 86400),
    add column hint_count integer not null default 0 check(hint_count between 0 and 100);
alter table public.grading_results add column response_seconds double precision check(response_seconds between 0 and 86400),
    add column hint_count integer not null default 0 check(hint_count between 0 and 100);

create function public.guard_adaptive_grade() returns trigger language plpgsql set search_path=public as $$
declare attempt public.exam_attempts; mode text; state jsonb; streak integer; total integer; corrects integer; mistakes integer; reason text; recent jsonb; recent_correct integer;
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
create trigger adaptive_grade_guard before insert on public.grading_results for each row execute function public.guard_adaptive_grade();

create function public.resume_adaptive_quiz(p_user_id uuid,p_attempt_id uuid,p_note text)
returns public.exam_attempts language plpgsql set search_path=public as $$
declare saved public.exam_attempts;
begin
    if length(trim(p_note))<20 or length(p_note)>2000 then raise exception 'Review note required' using errcode='22023'; end if;
    select * into saved from exam_attempts where id=p_attempt_id and user_id=p_user_id for update;
    if not found then raise exception 'Attempt not found' using errcode='42501'; end if;
    if saved.status<>'in_progress' or saved.expires_at<now() then raise exception 'Attempt expired or ended' using errcode='23514'; end if;
    if not coalesce((saved.adaptive_state->>'paused')::boolean,false) then return saved; end if;
    update exam_attempts set adaptive_state=jsonb_build_object('paused',false,'count',0,'correctCount',0,
        'consecutiveWrong',0,'highConfidenceWrong',0,'resumedAt',now(),'remediationNote',trim(p_note),
        'resumeCount',coalesce((adaptive_state->>'resumeCount')::integer,0)+1)
        where id=saved.id returning * into saved;
    return saved;
end; $$;
revoke all on function public.resume_adaptive_quiz(uuid,uuid,text) from public,authenticated,anon;
grant execute on function public.resume_adaptive_quiz(uuid,uuid,text) to service_role;

-- Browser clients cannot forge grading, clear pause state or read fixed answers.
do $$ declare tab text; begin
    foreach tab in array array['exam_attempts','exam_responses','grading_results'] loop
        execute format('drop policy if exists "Users manage own %s" on public.%I',tab,tab);
        execute format('create policy "Owners read assessment %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
    end loop;
end $$;
-- The assessment mode and mastery evidence must also remain server controlled.
do $$ declare tab text; pol record; begin
    foreach tab in array array['exams','questions','exam_blueprints','knowledge_mastery','mastery_history'] loop
        for pol in select policyname from pg_policies where schemaname='public' and tablename=tab loop
            execute format('drop policy %I on public.%I',pol.policyname,tab);
        end loop;
        execute format('create policy "Owners read trusted %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
    end loop;
end $$;
drop policy if exists "Users read own question versions" on public.question_versions;
drop policy "Owners read assessment grading_results" on public.grading_results;
create policy "Owners read released grades" on public.grading_results for select to authenticated
using(user_id=auth.uid() and exists(select 1 from public.exam_attempts a join public.exams e on e.id=a.exam_id
    where a.id=attempt_id and a.user_id=auth.uid() and (a.status='graded' or e.assessment_mode='adaptive')));
commit;
