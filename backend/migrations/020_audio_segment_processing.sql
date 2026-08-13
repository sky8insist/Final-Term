create table if not exists public.audio_segments (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    subject_id uuid not null references public.subjects(id) on delete cascade,
    material_id uuid not null references public.materials(id) on delete cascade,
    asset_id uuid references public.material_assets(id) on delete set null,
    segment_index integer not null,
    start_time double precision not null,
    end_time double precision not null,
    status text not null default 'queued',
    attempts integer not null default 0,
    transcription jsonb,
    error_message text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint audio_segments_index_check check (segment_index >= 0),
    constraint audio_segments_time_check check (start_time >= 0 and end_time >= start_time),
    constraint audio_segments_status_check check (status in ('queued', 'transcribing', 'ready', 'failed')),
    constraint audio_segments_attempts_check check (attempts >= 0),
    constraint audio_segments_material_index_unique unique (material_id, segment_index)
);

create index if not exists audio_segments_user_material_status_idx
    on public.audio_segments (user_id, material_id, status, segment_index);

alter table public.audio_segments enable row level security;
drop policy if exists "Users manage own audio segments" on public.audio_segments;
create policy "Users manage own audio segments" on public.audio_segments
for all to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

drop trigger if exists audio_segments_set_updated_at on public.audio_segments;
create trigger audio_segments_set_updated_at before update on public.audio_segments
for each row execute function public.set_updated_at();
