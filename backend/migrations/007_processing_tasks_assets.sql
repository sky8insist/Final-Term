create extension if not exists pgcrypto;

alter table public.materials drop constraint if exists materials_status_check;
alter table public.materials add constraint materials_status_check check (
    status in ('uploaded', 'queued', 'parsing', 'embedding', 'indexing', 'processing', 'ready', 'failed')
);
alter table public.materials add column if not exists source_hash text;
create unique index if not exists materials_user_subject_hash_unique
    on public.materials (user_id, subject_id, source_hash)
    where source_hash is not null and status <> 'failed';

create table if not exists public.processing_tasks (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid references public.materials(id) on delete cascade,
    task_type text not null default 'material_ingestion',
    status text not null default 'queued',
    stage text not null default 'queued',
    progress integer not null default 0,
    attempts integer not null default 0,
    max_attempts integer not null default 3,
    idempotency_key text not null,
    error_code text,
    error_message text,
    metadata jsonb not null default '{}'::jsonb,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint processing_tasks_status_check check (status in ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    constraint processing_tasks_stage_check check (stage in ('queued', 'parsing', 'embedding', 'indexing', 'ready', 'failed', 'cancelled')),
    constraint processing_tasks_progress_check check (progress between 0 and 100),
    constraint processing_tasks_attempts_check check (attempts >= 0 and max_attempts > 0),
    constraint processing_tasks_idempotency_unique unique (user_id, idempotency_key)
);

create table if not exists public.material_assets (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid not null references public.materials(id) on delete cascade,
    asset_type text not null default 'original',
    bucket text not null,
    object_path text not null,
    content_type text not null,
    file_size bigint not null,
    sha256 text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint material_assets_size_check check (file_size >= 0),
    constraint material_assets_object_unique unique (bucket, object_path)
);

create index if not exists processing_tasks_user_created_idx on public.processing_tasks (user_id, created_at desc);
create index if not exists material_assets_material_idx on public.material_assets (user_id, material_id);

drop trigger if exists processing_tasks_set_updated_at on public.processing_tasks;
create trigger processing_tasks_set_updated_at before update on public.processing_tasks
for each row execute function public.set_updated_at();

alter table public.processing_tasks enable row level security;
alter table public.material_assets enable row level security;

drop policy if exists "Users manage own processing tasks" on public.processing_tasks;
create policy "Users manage own processing tasks" on public.processing_tasks
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop policy if exists "Users manage own material assets" on public.material_assets;
create policy "Users manage own material assets" on public.material_assets
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

insert into storage.buckets (id, name)
values ('study-materials', 'study-materials')
on conflict (id) do update set name = excluded.name;

-- Self-hosted Storage adds these columns in its own service migrations. Keep
-- this application migration compatible with both the minimal bootstrap
-- schema and hosted/current Storage schemas.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'storage' and table_name = 'buckets' and column_name = 'public'
    ) then
        execute 'update storage.buckets set public = false where id = ''study-materials''';
    end if;
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'storage' and table_name = 'buckets' and column_name = 'file_size_limit'
    ) then
        execute 'update storage.buckets set file_size_limit = 209715200 where id = ''study-materials''';
    end if;
end $$;

drop policy if exists "Users manage own study material objects" on storage.objects;
create policy "Users manage own study material objects" on storage.objects
for all to authenticated
using (bucket_id = 'study-materials' and (storage.foldername(name))[1] = auth.uid()::text)
with check (bucket_id = 'study-materials' and (storage.foldername(name))[1] = auth.uid()::text);
