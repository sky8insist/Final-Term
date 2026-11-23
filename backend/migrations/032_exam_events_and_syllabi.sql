begin;
create table public.syllabi (
    id uuid primary key default gen_random_uuid(), user_id uuid not null, subject_id uuid not null,
    title text not null, content jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    unique (id,user_id,subject_id),
    foreign key (subject_id,user_id) references public.subjects(id,user_id) on delete cascade
);
create table public.syllabus_topics (
    syllabus_id uuid not null, user_id uuid not null, subject_id uuid not null, knowledge_point_id uuid not null,
    primary key (syllabus_id,knowledge_point_id),
    foreign key (syllabus_id,user_id,subject_id) references public.syllabi(id,user_id,subject_id) on delete cascade,
    foreign key (knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id)
);
create table public.exam_events (
    id uuid primary key default gen_random_uuid(), user_id uuid not null, subject_id uuid not null,
    title text not null, exam_date date not null, syllabus_id uuid,
    status text not null default 'active' check (status in ('active','completed','archived')),
    created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
    unique (id,user_id,subject_id),
    foreign key (subject_id,user_id) references public.subjects(id,user_id) on delete cascade,
    foreign key (syllabus_id,user_id,subject_id) references public.syllabi(id,user_id,subject_id)
);
create table public.exam_topic_map (
    exam_event_id uuid not null, user_id uuid not null, subject_id uuid not null,
    knowledge_point_id uuid not null, weight numeric not null default 1 check (weight between 0 and 100),
    primary key (exam_event_id,knowledge_point_id),
    foreign key (exam_event_id,user_id,subject_id) references public.exam_events(id,user_id,subject_id) on delete cascade,
    foreign key (knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id)
);
create index exam_events_upcoming_idx on public.exam_events(user_id,subject_id,status,exam_date);
create trigger exam_events_updated before update on public.exam_events
    for each row execute function public.set_updated_at();
do $$ declare tab text; begin
    foreach tab in array array['syllabi','syllabus_topics','exam_events','exam_topic_map'] loop
        execute format('alter table public.%I enable row level security', tab);
        execute format('create policy "Users manage own %s" on public.%I for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid())', tab, tab);
    end loop;
end $$;

create function public.save_course_exam(p_user_id uuid, p_subject_id uuid, p_event_id uuid, p_values jsonb)
returns public.exam_events language plpgsql set search_path=public as $$
declare result public.exam_events; item jsonb;
begin
    if auth.role() is distinct from 'service_role' and auth.uid() is distinct from p_user_id then
        raise exception 'Owner mismatch' using errcode='42501';
    end if;
    if p_event_id is null then
        insert into exam_events(user_id,subject_id,title,exam_date,syllabus_id,status)
            values(p_user_id,p_subject_id,p_values->>'title',(p_values->>'exam_date')::date,
                (p_values->>'syllabus_id')::uuid,coalesce(p_values->>'status','active')) returning * into result;
    else
        update exam_events set title=p_values->>'title', exam_date=(p_values->>'exam_date')::date,
            syllabus_id=(p_values->>'syllabus_id')::uuid, status=coalesce(p_values->>'status','active')
            where id=p_event_id and user_id=p_user_id and subject_id=p_subject_id returning * into result;
        if not found then raise exception 'Exam event not found' using errcode='42501'; end if;
        delete from exam_topic_map where exam_event_id=result.id and user_id=p_user_id;
    end if;
    for item in select * from jsonb_array_elements(p_values->'topics') loop
        insert into exam_topic_map values(result.id,p_user_id,p_subject_id,
            (item->>'knowledge_point_id')::uuid,coalesce((item->>'weight')::numeric,1));
    end loop;
    return result;
end; $$;
revoke all on function public.save_course_exam(uuid,uuid,uuid,jsonb) from public;
grant execute on function public.save_course_exam(uuid,uuid,uuid,jsonb) to authenticated,service_role;

create function public.create_course_syllabus(p_user_id uuid,p_subject_id uuid,p_values jsonb)
returns public.syllabi language plpgsql set search_path=public as $$
declare result public.syllabi; topic_id text;
begin
    if auth.role() is distinct from 'service_role' and auth.uid() is distinct from p_user_id then
        raise exception 'Owner mismatch' using errcode='42501';
    end if;
    insert into syllabi(user_id,subject_id,title,content)
        values(p_user_id,p_subject_id,p_values->>'title',p_values->'content') returning * into result;
    for topic_id in select * from jsonb_array_elements_text(p_values->'topic_ids') loop
        insert into syllabus_topics values(result.id,p_user_id,p_subject_id,topic_id::uuid);
    end loop;
    return result;
end; $$;
revoke all on function public.create_course_syllabus(uuid,uuid,jsonb) from public;
grant execute on function public.create_course_syllabus(uuid,uuid,jsonb) to authenticated,service_role;
commit;
