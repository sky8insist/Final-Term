create extension if not exists pgcrypto;

create table if not exists public.chat_messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    role text not null,
    content text not null,
    citations jsonb not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    constraint chat_messages_role_check check (role in ('user', 'assistant')),
    constraint chat_messages_content_not_empty check (char_length(content) > 0),
    constraint chat_messages_citations_array_check check (jsonb_typeof(citations) = 'array')
);

create index if not exists chat_messages_user_subject_created_at_idx
    on public.chat_messages (user_id, subject_id, created_at);

create table if not exists public.review_progress (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    mastered_count integer not null default 0,
    total_count integer not null default 0,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint review_progress_user_subject_unique unique (user_id, subject_id),
    constraint review_progress_counts_non_negative check (
        mastered_count >= 0 and total_count >= 0 and mastered_count <= total_count
    ),
    constraint review_progress_metadata_object_check check (jsonb_typeof(metadata) = 'object')
);

create index if not exists review_progress_user_subject_idx
    on public.review_progress (user_id, subject_id);

drop trigger if exists review_progress_set_updated_at on public.review_progress;

create trigger review_progress_set_updated_at
before update on public.review_progress
for each row
execute function public.set_updated_at();

alter table public.chat_messages enable row level security;
alter table public.review_progress enable row level security;

drop policy if exists "Users can select own chat messages" on public.chat_messages;
drop policy if exists "Users can insert own chat messages" on public.chat_messages;
drop policy if exists "Users can update own chat messages" on public.chat_messages;
drop policy if exists "Users can delete own chat messages" on public.chat_messages;

create policy "Users can select own chat messages"
on public.chat_messages
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own chat messages"
on public.chat_messages
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own chat messages"
on public.chat_messages
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own chat messages"
on public.chat_messages
for delete
to authenticated
using (user_id = auth.uid());

drop policy if exists "Users can select own review progress" on public.review_progress;
drop policy if exists "Users can insert own review progress" on public.review_progress;
drop policy if exists "Users can update own review progress" on public.review_progress;
drop policy if exists "Users can delete own review progress" on public.review_progress;

create policy "Users can select own review progress"
on public.review_progress
for select
to authenticated
using (user_id = auth.uid());

create policy "Users can insert own review progress"
on public.review_progress
for insert
to authenticated
with check (user_id = auth.uid());

create policy "Users can update own review progress"
on public.review_progress
for update
to authenticated
using (user_id = auth.uid())
with check (user_id = auth.uid());

create policy "Users can delete own review progress"
on public.review_progress
for delete
to authenticated
using (user_id = auth.uid());
