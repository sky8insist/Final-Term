alter table public.model_call_logs
    add column if not exists trace_id text,
    add column if not exists acceptance_run_id text;

alter table public.operation_metrics
    add column if not exists request_id text,
    add column if not exists trace_id text,
    add column if not exists acceptance_run_id text;

create index if not exists model_call_logs_acceptance_run_idx
    on public.model_call_logs (acceptance_run_id, created_at desc);
create index if not exists operation_metrics_acceptance_run_idx
    on public.operation_metrics (acceptance_run_id, created_at desc);
