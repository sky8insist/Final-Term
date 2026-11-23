begin;
create index if not exists review_tasks_calendar_idx on public.review_tasks(user_id,scheduled_date,plan_id);
create table public.calendar_availability (
 user_id uuid not null references auth.users(id) on delete cascade,
 day date not null, minutes integer not null check(minutes between 0 and 1440),
 version integer not null default 1 check(version>0), primary key(user_id,day)
);
create table public.calendar_exam_proposals (
 id uuid primary key default gen_random_uuid(), user_id uuid not null, subject_id uuid not null,
 material_id uuid not null, fingerprint text not null, title text not null, exam_date date not null,
 scope_text text not null default '', evidence jsonb not null,
 event_id uuid, created_at timestamptz not null default now(),
 unique(user_id,material_id,fingerprint),
 foreign key(material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade,
 foreign key(event_id,user_id,subject_id) references public.exam_events(id,user_id,subject_id) on delete cascade
);
alter table public.calendar_availability enable row level security;
alter table public.calendar_exam_proposals enable row level security;
create policy "Read own calendar availability" on public.calendar_availability for select to authenticated using(user_id=auth.uid());
create policy "Read own exam proposals" on public.calendar_exam_proposals for select to authenticated using(user_id=auth.uid());
revoke all on public.calendar_availability,public.calendar_exam_proposals from public,anon,authenticated;
grant select on public.calendar_availability,public.calendar_exam_proposals to authenticated;
grant all on public.calendar_availability,public.calendar_exam_proposals to service_role;

create function public.save_calendar_availability(p_user uuid,p_day date,p_minutes integer,p_version integer) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved public.calendar_availability;
begin
 perform pg_advisory_xact_lock(hashtextextended('calendar:'||p_user::text,0));
 if p_day<(now() at time zone 'Asia/Shanghai')::date or p_day>(now() at time zone 'Asia/Shanghai')::date+365 then
  raise exception 'Availability must be within the next year' using errcode='22023'; end if;
 select * into saved from calendar_availability where user_id=p_user and day=p_day for update;
 if (found and saved.version<>p_version) or (not found and p_version<>0) then raise exception 'Availability changed' using errcode='40001'; end if;
 insert into calendar_availability(user_id,day,minutes) values(p_user,p_day,p_minutes)
 on conflict(user_id,day) do update set minutes=excluded.minutes,version=calendar_availability.version+1 returning * into saved;
 update study_plans set replan_required=true,replan_reason='calendar availability changed',version=version+1
 where user_id=p_user and status='active' and exam_date>=p_day;
 return to_jsonb(saved)-'user_id';
end $$;

-- Calendar capacity is shared across subjects, including concurrent plan generation.
alter function public.save_study_plan_v3(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) rename to save_study_plan_before_calendar;
revoke all on function public.save_study_plan_before_calendar(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) from public,anon,authenticated,service_role;
create function public.save_study_plan_v3(p_user_id uuid,p_subject_id uuid,p_plan_id uuid,p_expected_version integer,
 p_values jsonb,p_tasks jsonb,p_preserve boolean) returns public.study_plans
language plpgsql security definer set search_path=public as $$
declare saved public.study_plans;
begin
 perform pg_advisory_xact_lock(hashtextextended('calendar:'||p_user_id::text,0));
 saved:=public.save_study_plan_before_calendar(p_user_id,p_subject_id,p_plan_id,p_expected_version,p_values,p_tasks,p_preserve);
 if exists(select 1 from calendar_availability a where a.user_id=p_user_id
  and a.day in (select (v->>'scheduled_date')::date from jsonb_array_elements(p_tasks) v)
  and a.minutes < (select coalesce(sum(t.estimated_minutes),0) from review_tasks t join study_plans p on p.id=t.plan_id
   where t.user_id=p_user_id and p.status='active' and t.status<>'skipped' and t.scheduled_date=a.day)) then
  raise exception 'Shared calendar capacity changed or exceeded' using errcode='40001';
 end if;
 return saved;
end $$;

create function public.move_calendar_task(p_user uuid,p_task uuid,p_day date,p_version integer) returns jsonb
language plpgsql security definer set search_path=public as $$
declare task public.review_tasks; plan public.study_plans; capacity integer; used integer;
begin
 perform pg_advisory_xact_lock(hashtextextended('calendar:'||p_user::text,0));
 select p.* into plan from study_plans p join review_tasks t on t.plan_id=p.id where t.id=p_task and t.user_id=p_user for update of p;
 if not found then raise exception 'Task not found' using errcode='42501'; end if;
 select * into task from review_tasks where id=p_task and user_id=p_user for update;
 if plan.status<>'active' or plan.version<>p_version or task.source<>'system' or task.locked or task.status not in ('pending','overdue') then
  raise exception 'Task is protected or changed' using errcode='40001'; end if;
 if p_day<(now() at time zone 'Asia/Shanghai')::date or p_day>plan.exam_date then
  raise exception 'Target day outside plan range' using errcode='22023'; end if;
 select minutes into capacity from calendar_availability where user_id=p_user and day=p_day;
 if not found then raise exception 'Set target day availability first' using errcode='22023'; end if;
 select coalesce(sum(t.estimated_minutes),0) into used from review_tasks t join study_plans p on p.id=t.plan_id
 where t.user_id=p_user and p.status='active' and t.status<>'skipped' and t.scheduled_date=p_day and t.id<>p_task;
 if used+task.estimated_minutes>capacity then raise exception 'Insufficient shared capacity' using errcode='40001'; end if;
 update review_tasks set scheduled_date=p_day,status='pending',locked=true,
  metadata=metadata||jsonb_build_object('calendarPreviousDate',task.scheduled_date,'calendarMovedAt',now()) where id=p_task returning * into task;
 insert into study_plan_events(user_id,subject_id,plan_id,event_type,reason,details)
 values(p_user,task.subject_id,task.plan_id,'calendar_moved','用户在日历改期并锁定',jsonb_build_object('taskId',p_task,'date',p_day));
 return to_jsonb(task)-'user_id';
end $$;

create function public.calendar_plan_capacity(p_user uuid,p_start date,p_end date,p_plan uuid default null) returns jsonb
language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_object_agg(a.day::text,greatest(0,a.minutes-(select coalesce(sum(t.estimated_minutes),0)
 from review_tasks t join study_plans p on p.id=t.plan_id where t.user_id=p_user and p.status='active'
 and t.status<>'skipped' and t.scheduled_date=a.day and (p_plan is null or t.plan_id<>p_plan)))),'{}')
 from calendar_availability a where a.user_id=p_user and a.day between p_start and p_end;
$$;

create function public.confirm_calendar_exam(p_user uuid,p_id uuid,p_values jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare proposal public.calendar_exam_proposals; saved public.exam_events; canonical jsonb; ids uuid[];
begin
 select * into proposal from calendar_exam_proposals where id=p_id and user_id=p_user for update;
 if not found then raise exception 'Proposal not found' using errcode='42501'; end if;
 if proposal.event_id is not null then
  select * into saved from exam_events where id=proposal.event_id;
  return to_jsonb(saved)-'user_id';
 end if;
 select array_agg((v->>'id')::uuid) into ids from jsonb_array_elements(proposal.evidence) v;
 canonical:=note_source_citations(p_user,proposal.subject_id,ids);
 if canonical is distinct from proposal.evidence then raise exception 'Syllabus evidence changed' using errcode='40001'; end if;
 if coalesce(length(trim(p_values->>'title')),0) not between 1 and 300 or (p_values->>'exam_date')::date<(now() at time zone 'Asia/Shanghai')::date
  or coalesce(jsonb_array_length(p_values->'topics'),0)=0 then raise exception 'Invalid confirmed exam' using errcode='22023'; end if;
 if exists(select 1 from jsonb_array_elements(p_values->'topics') t left join knowledge_points k
   on k.id=(t->>'knowledge_point_id')::uuid and k.user_id=p_user and k.subject_id=proposal.subject_id and not k.archived where k.id is null) then
  raise exception 'Invalid exam topics' using errcode='22023'; end if;
 saved:=save_course_exam(p_user,proposal.subject_id,null,p_values||jsonb_build_object('status','active','syllabus_id',null));
 update calendar_exam_proposals set event_id=saved.id where id=p_id;
 return to_jsonb(saved)-'user_id';
end $$;

create function public.learning_calendar(p_user uuid,p_start date,p_end date,p_subject uuid default null) returns jsonb
language plpgsql security definer set search_path=public as $$
declare output jsonb;
begin
 if p_end<p_start or p_end-p_start>41 then raise exception 'Calendar range exceeds 42 days' using errcode='22023'; end if;
 if p_subject is not null and not exists(select 1 from subjects where id=p_subject and user_id=p_user) then
  raise exception 'Subject not found' using errcode='42501'; end if;
 select coalesce(jsonb_agg(jsonb_build_object('date',d.day::date,'minutes',a.minutes,'version',coalesce(a.version,0),
  'plannedMinutes',(select coalesce(sum(t.estimated_minutes),0) from review_tasks t join study_plans p on p.id=t.plan_id
    where t.user_id=p_user and p.status='active' and t.scheduled_date=d.day::date and t.status<>'skipped'),
  'tasks',(select coalesce(jsonb_agg(to_jsonb(t)-'user_id'||jsonb_build_object('planVersion',p.version,'planExamDate',p.exam_date) order by t.priority desc,t.id),'[]')
    from review_tasks t join study_plans p on p.id=t.plan_id where t.user_id=p_user and p.status='active' and t.scheduled_date=d.day::date and (p_subject is null or t.subject_id=p_subject)),
  'exams',(select coalesce(jsonb_agg(to_jsonb(e)-'user_id' order by e.title,e.id),'[]') from exam_events e where e.user_id=p_user and e.status='active' and e.exam_date=d.day::date and (p_subject is null or e.subject_id=p_subject)),
  'globalExamCount',(select count(*) from exam_events e where e.user_id=p_user and e.status='active' and e.exam_date=d.day::date),
  'dueCards',(select count(*) from flashcard_review_state s join flashcards c using(artifact_id,card_id,user_id,subject_id)
    left join knowledge_points k on k.id=c.knowledge_point_id
    where s.user_id=p_user and not c.archived and (k.id is null or not k.archived) and (p_subject is null or s.subject_id=p_subject)
     and greatest((s.next_review at time zone 'Asia/Shanghai')::date,(now() at time zone 'Asia/Shanghai')::date)=d.day::date),
  'dueSubjects',(select coalesce(jsonb_agg(to_jsonb(v) order by v.subject_id),'[]') from
    (select s.subject_id,count(*) as count from flashcard_review_state s join flashcards c using(artifact_id,card_id,user_id,subject_id)
     left join knowledge_points k on k.id=c.knowledge_point_id where s.user_id=p_user and not c.archived and (k.id is null or not k.archived)
     and (p_subject is null or s.subject_id=p_subject)
     and greatest((s.next_review at time zone 'Asia/Shanghai')::date,(now() at time zone 'Asia/Shanghai')::date)=d.day::date
     group by s.subject_id) v)
 ) order by d.day),'[]') into output
 from generate_series(p_start::timestamp,p_end::timestamp,interval '1 day') d(day)
 left join calendar_availability a on a.user_id=p_user and a.day=d.day::date;
 return output;
end $$;

revoke all on function public.save_calendar_availability(uuid,date,integer,integer), public.move_calendar_task(uuid,uuid,date,integer),
 public.confirm_calendar_exam(uuid,uuid,jsonb),public.learning_calendar(uuid,date,date,uuid),
 public.save_study_plan_v3(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) from public,anon,authenticated;
revoke all on function public.calendar_plan_capacity(uuid,date,date,uuid) from public,anon,authenticated;
grant execute on function public.save_calendar_availability(uuid,date,integer,integer), public.move_calendar_task(uuid,uuid,date,integer),
 public.confirm_calendar_exam(uuid,uuid,jsonb),public.learning_calendar(uuid,date,date,uuid),
 public.save_study_plan_v3(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) to service_role;
grant execute on function public.calendar_plan_capacity(uuid,date,date,uuid) to service_role;
notify pgrst,'reload schema';
commit;
