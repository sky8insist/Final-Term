create table if not exists public.operation_metrics (
    id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete cascade,
    task_id uuid references public.processing_tasks(id) on delete set null,
    material_id uuid references public.materials(id) on delete set null,
    operation text not null,
    stage text,
    status text not null,
    duration_ms integer not null default 0,
    pages integer,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint operation_metric_status_check check (status in ('succeeded','failed','cancelled'))
);

create index if not exists operation_metrics_user_created_idx
    on public.operation_metrics (user_id, created_at desc);
alter table public.operation_metrics enable row level security;
drop policy if exists "Users read own operation metrics" on public.operation_metrics;
create policy "Users read own operation metrics" on public.operation_metrics
    for select to authenticated using (user_id = auth.uid());
