begin;
create table public.study_sessions (
    id uuid primary key, user_id uuid not null, subject_id uuid not null, knowledge_point_id uuid not null,
    exam_event_id uuid, goal text not null, status text not null default 'planned'
        check(status in ('planned','active','completed','cancelled')),
    version integer not null default 1, current_step integer not null default 0,
    minutes integer not null check(minutes between 10 and 120),
    context jsonb not null default '{}'::jsonb, summary jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
    unique(id,user_id,subject_id),
    foreign key(knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id) on delete cascade,
    foreign key(exam_event_id,user_id,subject_id) references public.exam_events(id,user_id,subject_id) on delete cascade
);
create table public.study_session_steps (
    id uuid primary key, session_id uuid not null, user_id uuid not null, subject_id uuid not null,
    sequence_index integer not null check(sequence_index >= 0),
    kind text not null check(kind in ('notes','socratic','flashcards','quiz','mastery_check','remediation')),
    title text not null, estimated_minutes integer not null check(estimated_minutes > 0),
    status text not null default 'pending' check(status in ('pending','running','ready','completed','skipped')),
    output jsonb not null default '{}'::jsonb,
    unique(session_id,sequence_index),
    foreign key(session_id,user_id,subject_id) references public.study_sessions(id,user_id,subject_id) on delete cascade
);
create index study_sessions_owner_idx on public.study_sessions(user_id,subject_id,created_at desc);
alter table public.study_sessions enable row level security;
alter table public.study_session_steps enable row level security;
create policy "Owners read study sessions" on public.study_sessions for select to authenticated using(user_id=auth.uid());
create policy "Owners read session steps" on public.study_session_steps for select to authenticated using(user_id=auth.uid());
create trigger study_sessions_updated before update on public.study_sessions
    for each row execute function public.set_updated_at();

-- Only the trusted backend may change progression or install evaluated outputs.
create function public.save_guided_session(p_user_id uuid,p_values jsonb,p_expected_version integer)
returns public.study_sessions language plpgsql set search_path=public as $$
declare saved public.study_sessions; step jsonb; current_version integer;
begin
    if p_expected_version is null then
        insert into study_sessions(id,user_id,subject_id,knowledge_point_id,exam_event_id,goal,status,minutes,context)
        values((p_values->>'id')::uuid,p_user_id,(p_values->>'subject_id')::uuid,
            (p_values->>'knowledge_point_id')::uuid,(p_values->>'exam_event_id')::uuid,
            p_values->>'goal','planned',(p_values->>'minutes')::integer,p_values->'context') returning * into saved;
    else
        select version into current_version from study_sessions
            where id=(p_values->>'id')::uuid and user_id=p_user_id for update;
        if not found then raise exception 'Session not found' using errcode='42501'; end if;
        if current_version <> p_expected_version then raise exception 'Session changed; reload' using errcode='40001'; end if;
        update study_sessions set status=p_values->>'status',current_step=(p_values->>'current_step')::integer,
            version=version+1,summary=coalesce(p_values->'summary','{}'::jsonb)
            where id=(p_values->>'id')::uuid and user_id=p_user_id returning * into saved;
        delete from study_session_steps where session_id=saved.id;
    end if;
    for step in select * from jsonb_array_elements(p_values->'steps') loop
        insert into study_session_steps values((step->>'id')::uuid,saved.id,p_user_id,saved.subject_id,
            (step->>'sequence_index')::integer,step->>'kind',step->>'title',
            (step->>'estimated_minutes')::integer,coalesce(step->>'status','pending'),coalesce(step->'output','{}'::jsonb));
    end loop;
    return saved;
end; $$;
revoke all on function public.save_guided_session(uuid,jsonb,integer) from public,authenticated,anon;
grant execute on function public.save_guided_session(uuid,jsonb,integer) to service_role;
commit;
