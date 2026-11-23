begin;
create table public.topic_coverage (
    user_id uuid not null, subject_id uuid not null, knowledge_point_id uuid not null,
    covered_at timestamptz not null default now(),
    primary key (user_id, subject_id, knowledge_point_id),
    foreign key (knowledge_point_id, user_id, subject_id)
        references public.knowledge_points(id, user_id, subject_id) on delete cascade
);
alter table public.topic_coverage enable row level security;
create policy "Users manage own topic coverage" on public.topic_coverage for all to authenticated
    using (user_id = auth.uid()) with check (user_id = auth.uid());
commit;
