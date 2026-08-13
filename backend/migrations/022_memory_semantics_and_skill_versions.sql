alter table public.memory_entries
    add column if not exists embedding vector,
    add column if not exists embedding_model text,
    add column if not exists embedding_dimensions integer;

alter table public.memory_entries
    drop constraint if exists memory_entries_embedding_consistency_check;
alter table public.memory_entries
    add constraint memory_entries_embedding_consistency_check check (
        (embedding is null and embedding_model is null and embedding_dimensions is null)
        or
        (embedding is not null and embedding_model is not null
         and embedding_dimensions = vector_dims(embedding))
    );

alter table public.memory_write_requests
    add column if not exists importance integer not null default 50,
    add column if not exists source_event_id uuid references public.learning_events(id) on delete set null;

create table if not exists public.procedural_skill_versions (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    skill_id uuid not null references public.procedural_skills(id) on delete cascade,
    version integer not null,
    name text not null,
    description text not null,
    instructions text not null,
    confidence double precision not null,
    status text not null,
    created_at timestamptz not null default now(),
    constraint procedural_skill_version_unique unique (skill_id, version)
);

alter table public.procedural_skill_versions enable row level security;
drop policy if exists "Users manage own procedural skill versions" on public.procedural_skill_versions;
create policy "Users manage own procedural skill versions" on public.procedural_skill_versions
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

create or replace function public.find_similar_memory(
    query_embedding vector,
    target_user_id uuid,
    target_memory_target text,
    result_limit integer default 5
)
returns table(id uuid, similarity double precision)
language sql stable security invoker as $$
    select me.id, 1 - (me.embedding <=> query_embedding) as similarity
    from public.memory_entries me
    where me.user_id = target_user_id
      and me.target = target_memory_target
      and me.embedding is not null
      and vector_dims(me.embedding) = vector_dims(query_embedding)
    order by me.embedding <=> query_embedding
    limit least(greatest(result_limit, 1), 20);
$$;
