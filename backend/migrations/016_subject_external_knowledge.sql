alter table public.subjects
    add column if not exists external_knowledge_enabled boolean not null default false;
