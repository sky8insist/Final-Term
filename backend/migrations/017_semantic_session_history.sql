alter table public.chat_messages
    add column if not exists session_id uuid;

create index if not exists chat_messages_user_session_created_idx
    on public.chat_messages (user_id, session_id, created_at desc);

alter table public.session_summaries
    add column if not exists embedding vector,
    add column if not exists embedding_model text;

create index if not exists session_summaries_summary_trgm_idx
    on public.session_summaries using gin (summary gin_trgm_ops);

drop function if exists public.search_learning_sessions(text, uuid, integer);

create or replace function public.search_learning_sessions(
    query_text text,
    target_user_id uuid,
    result_limit integer default 10,
    query_embedding vector default null
)
returns table(session_id uuid, subject_id uuid, summary text, rank real, created_at timestamptz)
language sql stable security invoker as $$
  with summary_matches as (
    select ss.session_id, ss.subject_id, ss.summary,
           greatest(
             ts_rank_cd(ss.search_vector, websearch_to_tsquery('simple', query_text)),
             similarity(ss.summary, query_text),
             case when query_embedding is not null and ss.embedding is not null
                        and vector_dims(query_embedding) = vector_dims(ss.embedding)
                  then 1 - (ss.embedding <=> query_embedding) else 0 end
           )::real as rank,
           ss.created_at
    from public.session_summaries ss
    where ss.user_id = target_user_id
      and (
        ss.search_vector @@ websearch_to_tsquery('simple', query_text)
        or ss.summary % query_text
        or ss.summary ilike '%' || query_text || '%'
        or (query_embedding is not null and ss.embedding is not null
            and vector_dims(query_embedding) = vector_dims(ss.embedding))
      )
  ), history_matches as (
    select cm.session_id, cm.subject_id,
           string_agg(left(cm.content, 500), E'\n' order by cm.created_at) as summary,
           max(similarity(cm.content, query_text))::real as rank,
           max(cm.created_at) as created_at
    from public.chat_messages cm
    where cm.user_id = target_user_id and cm.session_id is not null
      and (cm.content % query_text or cm.content ilike '%' || query_text || '%')
    group by cm.session_id, cm.subject_id
  )
  select combined.session_id, combined.subject_id, combined.summary,
         combined.rank, combined.created_at
  from (
    select * from summary_matches
    union all
    select * from history_matches
  ) combined
  order by combined.rank desc, combined.created_at desc
  limit least(greatest(result_limit, 1), 50);
$$;
