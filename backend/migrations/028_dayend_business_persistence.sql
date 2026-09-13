create table if not exists public.dayend_runs (
    run_id text primary key,
    thread_id text not null,
    user_id text,
    status text not null,
    state_json jsonb not null,
    created_at timestamptz not null default now()
);

create table if not exists public.dayend_night_states (
    thread_id text primary key,
    user_id text,
    closure_json jsonb,
    planning_json jsonb,
    emotion_json jsonb,
    confirmation_json jsonb,
    updated_at timestamptz not null default now()
);

create index if not exists dayend_runs_user_created_idx
    on public.dayend_runs (user_id, created_at desc);
