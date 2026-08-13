create extension if not exists pgcrypto;

create table if not exists public.memory_entries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    target text not null,
    content text not null,
    content_hash text not null,
    confidence double precision not null default 1,
    source_event_id uuid,
    importance integer not null default 50,
    last_used_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint memory_target_check check (target in ('assistant_memory', 'user_profile')),
    constraint memory_content_length check (char_length(content) between 1 and 1000),
    constraint memory_confidence_check check (confidence between 0 and 1),
    constraint memory_importance_check check (importance between 0 and 100),
    constraint memory_entry_unique unique (user_id, target, content_hash)
);

create table if not exists public.memory_write_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    action text not null,
    target text not null,
    memory_entry_id uuid references public.memory_entries(id) on delete cascade,
    old_text text,
    content text,
    confidence double precision not null default 1,
    reason text,
    status text not null default 'pending',
    created_at timestamptz not null default now(),
    resolved_at timestamptz,
    constraint memory_write_action_check check (action in ('add', 'replace', 'remove')),
    constraint memory_write_target_check check (target in ('assistant_memory', 'user_profile')),
    constraint memory_write_status_check check (status in ('pending', 'approved', 'rejected'))
);

create table if not exists public.memory_snapshots (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    session_id uuid not null,
    assistant_memory text not null default '',
    user_profile text not null default '',
    assistant_chars integer not null default 0,
    user_chars integer not null default 0,
    created_at timestamptz not null default now(),
    constraint memory_snapshot_session_unique unique (user_id, session_id)
);

create table if not exists public.learning_events (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    session_id uuid,
    event_type text not null,
    knowledge_point_id uuid,
    payload jsonb not null default '{}'::jsonb,
    confidence double precision,
    created_at timestamptz not null default now()
);

create table if not exists public.session_summaries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    session_id uuid not null,
    summary text not null,
    search_vector tsvector generated always as (to_tsvector('simple', summary)) stored,
    started_at timestamptz,
    ended_at timestamptz,
    created_at timestamptz not null default now(),
    constraint session_summary_unique unique (user_id, session_id)
);

create table if not exists public.learner_profiles (
    user_id uuid primary key references auth.users(id) on delete cascade,
    display_name text,
    timezone text not null default 'Asia/Shanghai',
    level text not null default 'beginner',
    preferred_role text not null default 'auto',
    response_style text not null default 'balanced',
    daily_minutes integer not null default 60,
    exam_date date,
    memory_enabled boolean not null default true,
    write_approval boolean not null default false,
    metadata jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    constraint learner_daily_minutes_check check (daily_minutes between 5 and 1440)
);

create table if not exists public.knowledge_mastery (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    knowledge_key text not null,
    mastery double precision not null default 0.5,
    confidence double precision not null default 0,
    attempts integer not null default 0,
    correct_attempts integer not null default 0,
    last_reviewed_at timestamptz,
    next_review_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    updated_at timestamptz not null default now(),
    constraint mastery_range_check check (mastery between 0 and 1 and confidence between 0 and 1),
    constraint mastery_attempts_check check (attempts >= 0 and correct_attempts between 0 and attempts),
    constraint mastery_unique unique (user_id, subject_id, knowledge_key)
);

create table if not exists public.procedural_skills (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid references public.subjects(id) on delete cascade,
    name text not null,
    description text not null,
    instructions text not null,
    evidence_count integer not null default 1,
    confidence double precision not null default 0.5,
    status text not null default 'candidate',
    version integer not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint procedural_skill_status_check check (status in ('candidate', 'active', 'archived')),
    constraint procedural_skill_unique unique (user_id, name)
);

create index if not exists memory_entries_user_target_idx on public.memory_entries (user_id, target, importance desc);
create index if not exists memory_write_pending_idx on public.memory_write_requests (user_id, status, created_at);
create index if not exists learning_events_user_subject_idx on public.learning_events (user_id, subject_id, created_at desc);
create index if not exists session_summaries_search_idx on public.session_summaries using gin (search_vector);

do $$ declare table_name text;
begin
  foreach table_name in array array['memory_entries','memory_write_requests','memory_snapshots','learning_events','session_summaries','knowledge_mastery','procedural_skills']
  loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists "Users manage own %s" on public.%I', table_name, table_name);
    execute format('create policy "Users manage own %s" on public.%I for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid())', table_name, table_name);
  end loop;
end $$;

alter table public.learner_profiles enable row level security;
drop policy if exists "Users manage own learner profile" on public.learner_profiles;
create policy "Users manage own learner profile" on public.learner_profiles
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create or replace function public.search_learning_sessions(query_text text, target_user_id uuid, result_limit integer default 10)
returns table(session_id uuid, subject_id uuid, summary text, rank real, created_at timestamptz)
language sql stable security invoker as $$
  select ss.session_id, ss.subject_id, ss.summary,
         ts_rank_cd(ss.search_vector, websearch_to_tsquery('simple', query_text)), ss.created_at
  from public.session_summaries ss
  where ss.user_id = target_user_id
    and ss.search_vector @@ websearch_to_tsquery('simple', query_text)
  order by 4 desc, ss.created_at desc
  limit least(greatest(result_limit, 1), 50);
$$;
