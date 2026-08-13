create extension if not exists pgcrypto;

create table if not exists public.exam_blueprints (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade, title text not null,
    duration_minutes integer not null, total_points numeric(8,2) not null,
    specification jsonb not null, created_at timestamptz not null default now(),
    constraint blueprint_duration_check check (duration_minutes between 1 and 1440),
    constraint blueprint_points_check check (total_points > 0)
);

create table if not exists public.questions (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    question_type text not null, knowledge_key text not null, difficulty text not null,
    source_kind text not null default 'material', current_version integer not null default 1,
    status text not null default 'active', created_at timestamptz not null default now(),
    constraint question_type_check check (question_type in ('single_choice','multiple_choice','true_false','fill_blank','short_answer','calculation','essay')),
    constraint question_difficulty_check check (difficulty in ('easy','medium','hard')),
    constraint question_source_check check (source_kind in ('material','external','mixed'))
);

create table if not exists public.question_versions (
    id uuid primary key default gen_random_uuid(), question_id uuid not null references public.questions(id) on delete cascade,
    version integer not null, stem text not null, options jsonb not null default '[]'::jsonb,
    correct_answer jsonb not null, explanation text not null, citations jsonb not null default '[]'::jsonb,
    rubric jsonb, quality jsonb not null default '{}'::jsonb, created_at timestamptz not null default now(),
    constraint question_version_unique unique (question_id, version)
);

create table if not exists public.exams (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    blueprint_id uuid not null references public.exam_blueprints(id) on delete restrict,
    title text not null, version integer not null default 1, duration_minutes integer not null,
    total_points numeric(8,2) not null, status text not null default 'published', created_at timestamptz not null default now(),
    constraint exam_status_check check (status in ('draft','published','archived'))
);

create table if not exists public.exam_sections (
    id uuid primary key default gen_random_uuid(), exam_id uuid not null references public.exams(id) on delete cascade,
    title text not null, instructions text, sequence_index integer not null, points numeric(8,2) not null
);

create table if not exists public.exam_questions (
    exam_id uuid not null references public.exams(id) on delete cascade,
    section_id uuid not null references public.exam_sections(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    question_version integer not null, sequence_index integer not null, points numeric(8,2) not null,
    primary key (exam_id, question_id), constraint exam_question_points_check check (points > 0)
);

create table if not exists public.exam_attempts (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    exam_id uuid not null references public.exams(id) on delete cascade,
    status text not null default 'in_progress', started_at timestamptz not null default now(),
    submitted_at timestamptz, expires_at timestamptz not null, score numeric(8,2), max_score numeric(8,2),
    constraint exam_attempt_status_check check (status in ('in_progress','submitted','graded','expired'))
);

create table if not exists public.exam_responses (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    attempt_id uuid not null references public.exam_attempts(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    response jsonb not null, answered_at timestamptz not null default now(),
    constraint exam_response_unique unique (attempt_id, question_id)
);

create table if not exists public.grading_results (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    attempt_id uuid not null references public.exam_attempts(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    earned_points numeric(8,2) not null, max_points numeric(8,2) not null, is_correct boolean,
    feedback text not null, earned_criteria jsonb not null default '[]'::jsonb,
    missing_criteria jsonb not null default '[]'::jsonb, error_type text,
    created_at timestamptz not null default now(), constraint grading_unique unique (attempt_id, question_id)
);

create table if not exists public.wrong_answers (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    attempt_id uuid not null references public.exam_attempts(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    error_type text not null, diagnosis text not null, resolved boolean not null default false,
    review_count integer not null default 0, next_review_at timestamptz, created_at timestamptz not null default now(),
    constraint wrong_answer_unique unique (user_id, attempt_id, question_id)
);

do $$ declare table_name text;
begin
  foreach table_name in array array['exam_blueprints','questions','exams','exam_attempts','exam_responses','grading_results','wrong_answers']
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists "Users manage own %s" on public.%I', table_name, table_name);
    execute format('create policy "Users manage own %s" on public.%I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', table_name, table_name);
  end loop;
end $$;

alter table public.question_versions enable row level security;
alter table public.exam_sections enable row level security;
alter table public.exam_questions enable row level security;
drop policy if exists "Users read own question versions" on public.question_versions;
create policy "Users read own question versions" on public.question_versions for select to authenticated
using (exists(select 1 from public.questions q where q.id=question_id and q.user_id=auth.uid()));
drop policy if exists "Users read own exam sections" on public.exam_sections;
create policy "Users read own exam sections" on public.exam_sections for select to authenticated
using (exists(select 1 from public.exams e where e.id=exam_id and e.user_id=auth.uid()));
drop policy if exists "Users read own exam questions" on public.exam_questions;
create policy "Users read own exam questions" on public.exam_questions for select to authenticated
using (exists(select 1 from public.exams e where e.id=exam_id and e.user_id=auth.uid()));
