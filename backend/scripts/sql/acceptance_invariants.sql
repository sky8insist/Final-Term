\set ON_ERROR_STOP on
begin;

insert into auth.users (id) values
  ('10000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002');

insert into public.subjects (id, user_id, name) values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '线性代数'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '隔离学科');

insert into public.materials (id, user_id, subject_id, filename, content_type, file_size, status) values
  ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'matrix.pdf', 'application/pdf', 10, 'ready'),
  ('30000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'private.pdf', 'application/pdf', 10, 'ready');

insert into public.content_blocks
  (id, user_id, subject_id, material_id, block_type, content_text, structured_data,
   page_number, sequence_index, parser_name, parser_version, confidence, source_hash)
values
  ('40000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'table', '矩阵的特征值等于特征方程的根', '{"headers":["特征值"]}', 2, 0, 'acceptance', '1', 1, 'hash-own'),
  ('40000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 'paragraph', '其他用户私有内容', '{}', 1, 0, 'acceptance', '1', 1, 'hash-other');

insert into public.material_chunks
  (id, user_id, subject_id, material_id, content_block_id, chunk_index, content,
   block_type, page_number, bounding_box, start_time, end_time, metadata)
values
  ('60000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', 0, '矩阵的特征值', 'table', 2, '{"x0":10,"y0":20,"x1":100,"y1":40}', null, null, '{"confidence":1}'),
  ('60000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', '40000000-0000-0000-0000-000000000002', 0, '其他用户私有内容', 'paragraph', 1, null, null, null, '{}');

insert into public.audio_segments
  (user_id, subject_id, material_id, segment_index, start_time, end_time, status, attempts, transcription)
values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 0, 0, 600, 'ready', 1, '{"text":"第一段"}'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 0, 0, 600, 'failed', 1, null);

insert into public.knowledge_points
  (user_id, subject_id, knowledge_key, title, importance)
values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'eigenvalue', '特征值', 90),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'private-point', '私有知识点', 50);

insert into public.rubrics
  (user_id, subject_id, name, question_type, version, criteria, total_points)
values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'eigenvalue-short', 'short_answer', 1, '[{"description":"定义","points":5}]', 5),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'private-rubric', 'essay', 1, '[{"description":"私有","points":5}]', 5);

insert into public.session_summaries
  (user_id, subject_id, session_id, summary)
values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', '50000000-0000-0000-0000-000000000001', '学生需要重点复习矩阵特征值');

do $$
begin
  if not exists (
    select 1 from public.search_content_blocks(
      '特征值', '10000000-0000-0000-0000-000000000001',
      '20000000-0000-0000-0000-000000000001', null, array['table'], 0.5, 10
    ) where page_number = 2 and block_type = 'table'
  ) then
    raise exception 'Chinese structured retrieval invariant failed';
  end if;
  if not exists (
    select 1 from public.search_learning_sessions(
      '矩阵', '10000000-0000-0000-0000-000000000001', 10, null
    ) where session_id = '50000000-0000-0000-0000-000000000001'
  ) then
    raise exception 'Session history retrieval invariant failed';
  end if;
  if not exists (
    select 1 from public.material_chunks mc
    where mc.content_block_id = '40000000-0000-0000-0000-000000000001'
      and mc.block_type = 'table' and mc.page_number = 2
      and (mc.bounding_box ->> 'x0')::integer = 10
  ) then
    raise exception 'Traceable chunk location invariant failed';
  end if;
end $$;

set local role authenticated;
select set_config('request.jwt.claim.sub', '10000000-0000-0000-0000-000000000001', true);

do $$
begin
  if (select count(*) from public.subjects) <> 1 then
    raise exception 'Subject RLS isolation invariant failed';
  end if;
  if (select count(*) from public.content_blocks) <> 1 then
    raise exception 'Content block RLS isolation invariant failed';
  end if;
  if (select count(*) from public.material_chunks) <> 1 then
    raise exception 'Material chunk RLS isolation invariant failed';
  end if;
  if (select count(*) from public.audio_segments) <> 1 then
    raise exception 'Audio segment RLS isolation invariant failed';
  end if;
  if (select count(*) from public.knowledge_points) <> 1 then
    raise exception 'Knowledge point RLS isolation invariant failed';
  end if;
  if (select count(*) from public.rubrics) <> 1 then
    raise exception 'Rubric RLS isolation invariant failed';
  end if;
end $$;

rollback;
