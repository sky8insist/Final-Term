create table if not exists public.mastery_history (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    knowledge_key text not null,
    mastery double precision not null,
    confidence double precision not null,
    correct boolean not null,
    difficulty text not null,
    evidence jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    constraint mastery_history_range_check check (mastery between 0 and 1 and confidence between 0 and 1)
);

create index if not exists mastery_history_user_subject_created_idx
    on public.mastery_history (user_id, subject_id, created_at desc);

alter table public.mastery_history enable row level security;
drop policy if exists "Users manage own mastery history" on public.mastery_history;
create policy "Users manage own mastery history" on public.mastery_history
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());
