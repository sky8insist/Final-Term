create table if not exists public.model_call_logs (
    id uuid primary key default gen_random_uuid(), user_id uuid references auth.users(id) on delete set null,
    request_id text, capability text not null, provider text not null, model_name text not null,
    status text not null, latency_ms integer not null, input_tokens integer, output_tokens integer,
    estimated_cost numeric(12,6), error_code text, metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint model_call_status_check check (status in ('succeeded','failed'))
);
create index if not exists model_call_logs_created_idx on public.model_call_logs (created_at desc, capability);
alter table public.model_call_logs enable row level security;
drop policy if exists "Users read own model calls" on public.model_call_logs;
create policy "Users read own model calls" on public.model_call_logs for select to authenticated using (user_id=auth.uid());

create table if not exists public.security_events (
    id uuid primary key default gen_random_uuid(), user_id uuid references auth.users(id) on delete cascade,
    material_id uuid references public.materials(id) on delete cascade, event_type text not null,
    severity text not null, details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);
alter table public.security_events enable row level security;
drop policy if exists "Users read own security events" on public.security_events;
create policy "Users read own security events" on public.security_events for select to authenticated using (user_id=auth.uid());

alter table public.materials add column if not exists expires_at timestamptz;
alter table public.material_assets add column if not exists expires_at timestamptz;
