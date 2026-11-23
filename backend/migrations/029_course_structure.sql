-- Stable topic identity: display names may change; legacy knowledge_key stays immutable.
begin;

alter table public.subjects add constraint subjects_owner_scope_unique unique (id, user_id);
alter table public.knowledge_points add constraint knowledge_points_scope_unique unique (id, user_id, subject_id);

create table public.knowledge_units (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null,
    title text not null check (length(trim(title)) between 1 and 300),
    sequence_index integer not null default 0 check (sequence_index >= 0),
    created_at timestamptz not null default now(),
    unique (id, user_id, subject_id),
    foreign key (subject_id, user_id) references public.subjects(id, user_id) on delete cascade
);

alter table public.knowledge_points
    add column unit_id uuid,
    add column sequence_index integer not null default 0 check (sequence_index >= 0),
    add column syllabus_weight numeric not null default 1 check (syllabus_weight between 0 and 100),
    add column source_refs jsonb not null default '[]'::jsonb check (jsonb_typeof(source_refs) = 'array'),
    add column archived boolean not null default false,
    add constraint knowledge_point_unit_scope foreign key (unit_id, user_id, subject_id)
        references public.knowledge_units(id, user_id, subject_id),
    add constraint knowledge_point_subject_scope foreign key (subject_id, user_id)
        references public.subjects(id, user_id) on delete cascade;

create table public.topic_aliases (
    user_id uuid not null,
    subject_id uuid not null,
    alias text not null check (length(alias) between 1 and 300),
    knowledge_point_id uuid not null,
    primary key (user_id, subject_id, alias),
    foreign key (knowledge_point_id, user_id, subject_id)
        references public.knowledge_points(id, user_id, subject_id) on delete cascade
);

-- Existing IDs and mastery keys are preserved. Ambiguous legacy aliases resolve
-- deterministically, rather than silently deleting/merging historical records.
insert into public.topic_aliases (user_id, subject_id, alias, knowledge_point_id)
select distinct on (user_id, subject_id, alias) user_id, subject_id, alias, id
from (
    select id, user_id, subject_id, created_at,
        lower(regexp_replace(trim(knowledge_key), '\s+', ' ', 'g')) as alias
    from public.knowledge_points
    union all
    select id, user_id, subject_id, created_at,
        lower(regexp_replace(trim(title), '\s+', ' ', 'g'))
    from public.knowledge_points
) aliases where length(alias) between 1 and 300
order by user_id, subject_id, alias, created_at, id;

alter table public.review_tasks add column knowledge_point_id uuid,
    add constraint review_task_topic_scope foreign key (knowledge_point_id, user_id, subject_id)
        references public.knowledge_points(id, user_id, subject_id);
update public.review_tasks t set knowledge_point_id = a.knowledge_point_id
from public.topic_aliases a where a.user_id = t.user_id and a.subject_id = t.subject_id
    and a.alias = lower(regexp_replace(trim(t.knowledge_key), '\s+', ' ', 'g'));

create table public.artifact_topics (
    artifact_id uuid not null references public.artifacts(id) on delete cascade,
    user_id uuid not null, subject_id uuid not null, knowledge_point_id uuid not null,
    primary key (artifact_id, knowledge_point_id),
    foreign key (knowledge_point_id, user_id, subject_id)
        references public.knowledge_points(id, user_id, subject_id) on delete cascade
);
alter table public.artifacts add constraint artifacts_scope_unique unique (id, user_id, subject_id);
alter table public.artifact_topics add constraint artifact_topic_owner_scope
    foreign key (artifact_id, user_id, subject_id)
    references public.artifacts(id, user_id, subject_id) on delete cascade;

create index knowledge_units_scope_order_idx on public.knowledge_units(user_id, subject_id, sequence_index);
create index knowledge_points_unit_order_idx on public.knowledge_points(user_id, subject_id, unit_id, sequence_index);
create index review_tasks_topic_idx on public.review_tasks(knowledge_point_id);

alter table public.knowledge_units enable row level security;
alter table public.topic_aliases enable row level security;
alter table public.artifact_topics enable row level security;
create policy "Users manage own units" on public.knowledge_units for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "Users manage own aliases" on public.topic_aliases for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
create policy "Users manage own artifact topics" on public.artifact_topics for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());

-- One transaction resolves aliases and creates topics, including concurrent generation.
create function public.resolve_course_topic(p_user_id uuid, p_subject_id uuid, p_title text, p_details jsonb default '{}'::jsonb)
returns public.knowledge_points language plpgsql set search_path = public as $$
declare result public.knowledge_points; normalized text;
begin
    if auth.role() is distinct from 'service_role' and auth.uid() is distinct from p_user_id then
        raise exception 'Topic owner mismatch' using errcode = '42501';
    end if;
    normalized := lower(regexp_replace(trim(p_title), '\s+', ' ', 'g'));
    if length(normalized) not between 1 and 300 then
        raise exception 'Invalid topic title' using errcode = '22023';
    end if;
    if not exists (select 1 from subjects where id = p_subject_id and user_id = p_user_id) then
        raise exception 'Subject not found' using errcode = '42501';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text || p_subject_id::text || normalized, 0));
    select kp.* into result from topic_aliases a join knowledge_points kp on kp.id = a.knowledge_point_id
        where a.user_id = p_user_id and a.subject_id = p_subject_id and a.alias = normalized;
    if found then return result; end if;
    insert into knowledge_points(user_id, subject_id, knowledge_key, title, unit_id, sequence_index, syllabus_weight, source_refs)
        values (p_user_id, p_subject_id, trim(p_title), trim(p_title),
            (p_details->>'unit_id')::uuid, coalesce((p_details->>'sequence_index')::integer, 0),
            coalesce((p_details->>'syllabus_weight')::numeric, 1), coalesce(p_details->'source_refs', '[]'::jsonb))
        on conflict (user_id, subject_id, knowledge_key) do update
        set knowledge_key = excluded.knowledge_key returning * into result;
    insert into topic_aliases values (p_user_id, p_subject_id, normalized, result.id);
    return result;
end;
$$;
revoke all on function public.resolve_course_topic(uuid, uuid, text, jsonb) from public;
grant execute on function public.resolve_course_topic(uuid, uuid, text, jsonb) to authenticated, service_role;
commit;
