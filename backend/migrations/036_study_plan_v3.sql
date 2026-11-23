begin;
alter table public.study_plans add column version integer not null default 1 check(version>0),
    add column mode text not null default 'STANDARD' check(mode in ('CRAM','STANDARD','COMPREHENSIVE')),
    add column exam_event_id uuid,
    add column replan_required boolean not null default false,
    add column replan_reason text,
    add constraint study_plan_scope_unique unique(id,user_id,subject_id),
    add foreign key(exam_event_id,user_id,subject_id) references public.exam_events(id,user_id,subject_id);
alter table public.review_tasks add column locked boolean not null default false,
    add foreign key(plan_id,user_id,subject_id) references public.study_plans(id,user_id,subject_id) on delete cascade;
create table public.study_plan_events (
    id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,plan_id uuid not null,
    event_type text not null,reason text not null,details jsonb not null default '{}'::jsonb,created_at timestamptz not null default now(),
    foreign key(plan_id,user_id,subject_id) references public.study_plans(id,user_id,subject_id) on delete cascade
);
alter table public.study_plan_events enable row level security;
create policy "Owners read plan events" on public.study_plan_events for select to authenticated using(user_id=auth.uid());
create index study_plan_events_owner_idx on public.study_plan_events(user_id,plan_id,created_at desc);
drop policy "Users manage own study_plans" on public.study_plans;
drop policy "Users manage own review_tasks" on public.review_tasks;
create policy "Owners read plans" on public.study_plans for select to authenticated using(user_id=auth.uid());
create policy "Owners read review tasks" on public.review_tasks for select to authenticated using(user_id=auth.uid());

create function public.save_study_plan_v3(p_user_id uuid,p_subject_id uuid,p_plan_id uuid,p_expected_version integer,
    p_values jsonb,p_tasks jsonb,p_preserve boolean) returns public.study_plans language plpgsql set search_path=public as $$
declare saved public.study_plans; task jsonb; previous_flag text;
begin
    if not exists(select 1 from subjects where id=p_subject_id and user_id=p_user_id) then
        raise exception 'Subject not found' using errcode='42501'; end if;
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text||':'||p_subject_id::text,0));
    if p_plan_id is not null then
        select * into saved from study_plans where id=p_plan_id and user_id=p_user_id and subject_id=p_subject_id for update;
        if not found or saved.version<>p_expected_version then raise exception 'Plan changed' using errcode='40001'; end if;
    elsif exists(select 1 from study_plans where user_id=p_user_id and subject_id=p_subject_id and status='active') then
        raise exception 'Plan created concurrently' using errcode='40001';
    end if;
    previous_flag:=current_setting('app.plan_generation',true);
    perform set_config('app.plan_generation','on',true);
    if p_plan_id is not null and not p_preserve then
        update study_plans set status='archived',version=version+1 where id=saved.id;
        p_plan_id:=null;
    end if;
    if p_plan_id is null then
        insert into study_plans(user_id,subject_id,title,exam_date,daily_minutes,strategy,mode,exam_event_id)
        values(p_user_id,p_subject_id,p_values->>'title',(p_values->>'exam_date')::date,(p_values->>'daily_minutes')::integer,
            p_values->'strategy',p_values->>'mode',(p_values->>'exam_event_id')::uuid) returning * into saved;
    else
        delete from review_tasks where plan_id=saved.id and user_id=p_user_id and status<>'completed' and source<>'user' and not locked;
        update study_plans set title=p_values->>'title',exam_date=(p_values->>'exam_date')::date,
            daily_minutes=(p_values->>'daily_minutes')::integer,strategy=p_values->'strategy',mode=p_values->>'mode',
            exam_event_id=(p_values->>'exam_event_id')::uuid,version=version+1,replan_required=false,replan_reason=null,
            updated_at=now() where id=saved.id returning * into saved;
    end if;
    for task in select * from jsonb_array_elements(p_tasks) loop
        insert into review_tasks(user_id,subject_id,plan_id,knowledge_key,knowledge_point_id,task_type,title,
            scheduled_date,estimated_minutes,priority,status,source,metadata)
        values(p_user_id,p_subject_id,saved.id,task->>'knowledge_key',(task->>'knowledge_point_id')::uuid,
            task->>'task_type',task->>'title',(task->>'scheduled_date')::date,(task->>'estimated_minutes')::integer,
            (task->>'priority')::double precision,'pending','system',task->'metadata');
    end loop;
    insert into study_plan_events(user_id,subject_id,plan_id,event_type,reason,details)
        values(p_user_id,p_subject_id,saved.id,'replanned',coalesce(p_values->>'reason','用户生成计划'),
            jsonb_build_object('version',saved.version,'mode',saved.mode,'taskCount',jsonb_array_length(p_tasks),
                'dailyUsage',p_values->'strategy'->'dailyUsage','preservedTaskCount',p_values->'strategy'->'preservedTaskCount'));
    perform set_config('app.plan_generation',coalesce(previous_flag,''),true);
    return saved;
end; $$;
revoke all on function public.save_study_plan_v3(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) from public,anon,authenticated;
grant execute on function public.save_study_plan_v3(uuid,uuid,uuid,integer,jsonb,jsonb,boolean) to service_role;

create function public.mark_study_plan_changed() returns trigger language plpgsql set search_path=public as $$
declare owner_id uuid; course_id uuid; item jsonb; plan_row record; reason text;
begin
    if current_setting('app.plan_generation',true)='on' then return null; end if;
    if tg_table_name='review_tasks' and tg_op='UPDATE' and
        (to_jsonb(old)-'metadata'-'updated_at')=(to_jsonb(new)-'metadata'-'updated_at') then return null; end if;
    item:=case when tg_op='DELETE' then to_jsonb(old) else to_jsonb(new) end;
    owner_id:=(item->>'user_id')::uuid; course_id:=(item->>'subject_id')::uuid;
    if tg_table_name='materials' and item->>'status'<>'ready' then return null; end if;
    reason:=tg_table_name||':'||lower(tg_op);
    for plan_row in update study_plans set replan_required=true,replan_reason=reason,version=version+1
        where user_id=owner_id and subject_id=course_id and status='active'
            and strategy->>'algorithmVersion'='exam-state-scheduler-v3' returning id loop
        insert into study_plan_events(user_id,subject_id,plan_id,event_type,reason)
            values(owner_id,course_id,plan_row.id,'signal_changed',reason);
    end loop;
    return null;
end; $$;
do $$ declare tab text; begin
    foreach tab in array array['knowledge_mastery','topic_coverage','exam_events','exam_topic_map','review_tasks','knowledge_points','syllabus_topics'] loop
        execute format('create trigger study_plan_changed after insert or update or delete on public.%I for each row execute function public.mark_study_plan_changed()',tab);
    end loop;
end $$;
create trigger study_plan_material_ready after update of status on public.materials for each row
    when(old.status is distinct from new.status) execute function public.mark_study_plan_changed();
create function public.study_plan_replan_candidates() returns setof public.study_plans language sql set search_path=public as $$
    select p.* from study_plans p where p.status='active' and p.exam_date>(now() at time zone 'Asia/Shanghai')::date
        and p.strategy->>'algorithmVersion'='exam-state-scheduler-v3' and p.strategy->>'autoReplan'='true'
        and (p.replan_required or exists(select 1 from review_tasks t where t.plan_id=p.id and t.user_id=p.user_id
            and t.source='system' and not t.locked and t.status='pending' and t.scheduled_date<(now() at time zone 'Asia/Shanghai')::date))
    order by p.updated_at limit 20;
$$;
revoke all on function public.study_plan_replan_candidates() from public,anon,authenticated;
grant execute on function public.study_plan_replan_candidates() to service_role;
commit;
