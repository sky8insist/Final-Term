create table if not exists public.knowledge_points (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    knowledge_key text not null,
    title text not null,
    description text,
    chapter text,
    importance integer not null default 50,
    prerequisites jsonb not null default '[]'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint knowledge_point_importance_check check (importance between 0 and 100),
    constraint knowledge_point_user_subject_key_unique unique (user_id, subject_id, knowledge_key)
);

create table if not exists public.rubrics (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    name text not null,
    question_type text not null,
    version integer not null default 1,
    criteria jsonb not null,
    total_points numeric(8,2) not null,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    constraint rubric_question_type_check check (question_type in ('short_answer','calculation','essay')),
    constraint rubric_version_check check (version > 0),
    constraint rubric_total_points_check check (total_points > 0),
    constraint rubric_status_check check (status in ('active','archived')),
    constraint rubric_user_name_version_unique unique (user_id, subject_id, name, version)
);

alter table public.questions
    add column if not exists knowledge_point_id uuid references public.knowledge_points(id) on delete set null;

alter table public.question_versions
    add column if not exists rubric_id uuid references public.rubrics(id) on delete set null;

insert into public.knowledge_points (user_id, subject_id, knowledge_key, title)
select distinct q.user_id, q.subject_id, q.knowledge_key, q.knowledge_key
from public.questions q
where q.knowledge_key is not null and trim(q.knowledge_key) <> ''
on conflict (user_id, subject_id, knowledge_key) do nothing;

update public.questions q
set knowledge_point_id = kp.id
from public.knowledge_points kp
where q.knowledge_point_id is null
  and kp.user_id = q.user_id
  and kp.subject_id = q.subject_id
  and kp.knowledge_key = q.knowledge_key;

create index if not exists knowledge_points_user_subject_idx
    on public.knowledge_points (user_id, subject_id, chapter, importance desc);
create index if not exists rubrics_user_subject_type_idx
    on public.rubrics (user_id, subject_id, question_type, status, version desc);
create index if not exists questions_knowledge_point_idx
    on public.questions (knowledge_point_id);

alter table public.knowledge_points enable row level security;
alter table public.rubrics enable row level security;
drop policy if exists "Users manage own knowledge points" on public.knowledge_points;
create policy "Users manage own knowledge points" on public.knowledge_points
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists "Users manage own rubrics" on public.rubrics;
create policy "Users manage own rubrics" on public.rubrics
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop trigger if exists knowledge_points_set_updated_at on public.knowledge_points;
create trigger knowledge_points_set_updated_at before update on public.knowledge_points
for each row execute function public.set_updated_at();
