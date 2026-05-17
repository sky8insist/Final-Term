create extension if not exists vector;

alter table public.material_chunks
    add column if not exists embedding vector,
    add column if not exists embedding_model text,
    add column if not exists embedding_dimensions integer,
    add column if not exists embedded_at timestamptz;

alter table public.material_chunks
    drop constraint if exists material_chunks_embedding_consistency_check;

alter table public.material_chunks
    add constraint material_chunks_embedding_consistency_check
    check (
        (
            embedding is null
            and embedding_model is null
            and embedding_dimensions is null
            and embedded_at is null
        )
        or
        (
            embedding is not null
            and embedding_model is not null
            and embedding_dimensions is not null
            and embedded_at is not null
            and embedding_dimensions = vector_dims(embedding)
        )
    );
