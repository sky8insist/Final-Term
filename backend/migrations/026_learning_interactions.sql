alter table public.chat_messages
    add column if not exists metadata jsonb not null default '{}'::jsonb;

alter table public.chat_messages
    drop constraint if exists chat_messages_metadata_object_check;

alter table public.chat_messages
    add constraint chat_messages_metadata_object_check
    check (jsonb_typeof(metadata) = 'object');

create table if not exists public.learning_interactions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    session_id uuid not null,
    interaction_type text not null default 'socratic',
    source_mode text not null default 'socratic',
    status text not null default 'awaiting_answer',
    question_id uuid references public.questions(id) on delete set null,
    attempt_id uuid references public.exam_attempts(id) on delete set null,
    parent_interaction_id uuid references public.learning_interactions(id) on delete set null,
    knowledge_key text,
    question_text text not null,
    expected_response_type text not null default 'reasoning',
    source_query text,
    current_step integer not null default 0,
    attempt_count integer not null default 0,
    evidence jsonb not null default '{}'::jsonb,
    metadata jsonb not null default '{}'::jsonb,
    expires_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint learning_interaction_type_check check (
        interaction_type in ('socratic','practice','exam_review','wrong_answer_review')
    ),
    constraint learning_interaction_status_check check (
        status in ('awaiting_answer','awaiting_clarification','suspended','completed','abandoned','expired')
    ),
    constraint learning_interaction_mode_check check (
        source_mode in ('beginner','crash_course','socratic','examiner','mistake_coach','academic','sprint_planner')
    ),
    constraint learning_interaction_attempt_check check (attempt_count >= 0 and current_step >= 0),
    constraint learning_interaction_evidence_object_check check (jsonb_typeof(evidence) = 'object'),
    constraint learning_interaction_metadata_object_check check (jsonb_typeof(metadata) = 'object')
);

create index if not exists learning_interactions_active_session_idx
    on public.learning_interactions (user_id, subject_id, session_id, updated_at desc)
    where status in ('awaiting_answer','awaiting_clarification','suspended');

drop trigger if exists learning_interactions_set_updated_at on public.learning_interactions;
create trigger learning_interactions_set_updated_at
before update on public.learning_interactions
for each row execute function public.set_updated_at();

alter table public.learning_interactions enable row level security;

-- Interaction evidence can contain hidden answers and rubrics. It is accessed
-- only by the trusted backend service role; authenticated browser clients get
-- no direct table policy.
revoke all on table public.learning_interactions from authenticated;

