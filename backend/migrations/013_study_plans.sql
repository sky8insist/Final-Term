create table if not exists public.study_plans (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    title text not null, exam_date date not null, daily_minutes integer not null,
    status text not null default 'active', strategy jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
    constraint study_plan_daily_check check (daily_minutes between 5 and 1440),
    constraint study_plan_status_check check (status in ('active','completed','archived'))
);

create table if not exists public.review_tasks (
    id uuid primary key default gen_random_uuid(), user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    plan_id uuid references public.study_plans(id) on delete cascade,
    knowledge_key text not null, task_type text not null, title text not null,
    scheduled_date date not null, estimated_minutes integer not null, priority double precision not null,
    status text not null default 'pending', source text not null default 'system',
    completed_at timestamptz, metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
    constraint review_task_status_check check (status in ('pending','completed','skipped','overdue')),
    constraint review_task_minutes_check check (estimated_minutes between 1 and 1440),
    constraint review_task_unique unique (user_id, plan_id, knowledge_key, scheduled_date, task_type)
);

do $$ declare table_name text;
begin
  foreach table_name in array array['study_plans','review_tasks'] loop
    execute format('alter table public.%I enable row level security', table_name);
    execute format('drop policy if exists "Users manage own %s" on public.%I', table_name, table_name);
    execute format('create policy "Users manage own %s" on public.%I for all to authenticated using (user_id=auth.uid()) with check (user_id=auth.uid())', table_name, table_name);
  end loop;
end $$;
create index if not exists review_tasks_today_idx on public.review_tasks (user_id, scheduled_date, status, priority desc);
