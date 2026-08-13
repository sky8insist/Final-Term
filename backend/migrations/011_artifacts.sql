create extension if not exists pgcrypto;

create table if not exists public.artifacts (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    artifact_type text not null,
    title text not null,
    content jsonb not null,
    citations jsonb not null default '[]'::jsonb,
    generation_params jsonb not null default '{}'::jsonb,
    model_name text,
    prompt_version text not null default '1.0.0',
    version integer not null default 1,
    is_user_edited boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint artifact_type_check check (artifact_type in ('outline', 'mind_map', 'flashcards', 'formula_sheet', 'glossary', 'comparison', 'cheat_sheet')),
    constraint artifact_version_check check (version > 0)
);

create index if not exists artifacts_user_subject_created_idx on public.artifacts (user_id, subject_id, created_at desc);
alter table public.artifacts enable row level security;
drop policy if exists "Users manage own artifacts" on public.artifacts;
create policy "Users manage own artifacts" on public.artifacts
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop trigger if exists artifacts_set_updated_at on public.artifacts;
create trigger artifacts_set_updated_at before update on public.artifacts
for each row execute function public.set_updated_at();
