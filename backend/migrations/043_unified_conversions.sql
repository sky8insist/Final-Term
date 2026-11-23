begin;
alter table public.processing_tasks add constraint conversion_task_scope unique(id,user_id,subject_id);
alter table public.exams add constraint conversion_exam_scope unique(id,user_id,subject_id);
alter table public.wrong_answers add constraint conversion_wrong_scope unique(id,user_id,subject_id);
create table public.learning_conversions (
 id uuid primary key, user_id uuid not null, subject_id uuid not null,
 request_id uuid not null, fingerprint text not null,
 source_kind text not null check(source_kind in ('material','notes','mind_map_node','wrong_answer')),
 source_material_id uuid, source_artifact_id uuid, source_wrong_answer_id uuid,
 source_version integer, source_node_id text,
 target text not null check(target in ('notes','flashcards','mind_map','quiz','tutor')),
 options jsonb not null, snapshot jsonb not null,
 claim_token uuid, result_artifact_id uuid unique, result_exam_id uuid unique, result_href text,
 created_at timestamptz not null default now(),
 unique(user_id,request_id),
 check(num_nonnulls(source_material_id,source_artifact_id,source_wrong_answer_id)=1),
 check((source_kind='material' and source_material_id is not null and source_version is null and source_node_id is null)
    or (source_kind='wrong_answer' and source_wrong_answer_id is not null and source_version is null and source_node_id is null)
    or (source_kind='notes' and source_artifact_id is not null and source_version>0 and source_node_id is null)
    or (source_kind='mind_map_node' and source_artifact_id is not null and source_version>0 and length(source_node_id)>0)),
 foreign key(subject_id,user_id) references public.subjects(id,user_id) on delete cascade,
 foreign key(id,user_id,subject_id) references public.processing_tasks(id,user_id,subject_id) on delete cascade,
 foreign key(source_material_id,user_id,subject_id) references public.materials(id,user_id,subject_id) on delete cascade,
 foreign key(source_artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade,
 foreign key(source_wrong_answer_id,user_id,subject_id) references public.wrong_answers(id,user_id,subject_id) on delete cascade,
 foreign key(result_artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade,
 foreign key(result_exam_id,user_id,subject_id) references public.exams(id,user_id,subject_id) on delete cascade
);
create index conversions_source_artifact on public.learning_conversions(user_id,source_artifact_id,created_at desc);
create index conversions_source_material on public.learning_conversions(user_id,source_material_id,created_at desc);
create index conversions_source_wrong_answer on public.learning_conversions(user_id,source_wrong_answer_id,created_at desc);
create index conversions_subject on public.learning_conversions(user_id,subject_id,created_at desc);
alter table public.learning_conversions enable row level security;
create policy "Owners read conversions" on public.learning_conversions for select to authenticated using(user_id=auth.uid());
revoke all on public.learning_conversions from anon,authenticated;
grant select on public.learning_conversions to authenticated;
grant all on public.learning_conversions to service_role;

create function public.enqueue_conversion(p_user_id uuid,p_subject_id uuid,p_request_id uuid,p_fingerprint text,
 p_source jsonb,p_target text,p_options jsonb,p_snapshot jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved public.learning_conversions; task_id uuid; root public.artifacts; source_id uuid;
begin
 perform pg_advisory_xact_lock(hashtextextended(p_user_id::text||p_request_id::text,0));
 select * into saved from public.learning_conversions where user_id=p_user_id and request_id=p_request_id;
 if found then
  if saved.fingerprint<>p_fingerprint then raise exception 'Request ID reused with different parameters' using errcode='40001'; end if;
  return to_jsonb(saved)-'user_id'-'claim_token';
 end if;
 if not exists(select 1 from public.subjects where id=p_subject_id and user_id=p_user_id) then
  raise exception 'Source not found' using errcode='42501';
 end if;
 source_id:=(p_source->>'id')::uuid;
 if (p_options->>'count')::integer not between 1 and 20
  or p_options->>'mode' not in ('summary','standard','comprehensive','exam_focus')
  or coalesce(jsonb_array_length(p_snapshot->'citations'),0) not between 1 and 30
  or not (case p_source->>'kind'
   when 'material' then p_target in ('notes','flashcards','mind_map','quiz')
   when 'notes' then p_target in ('flashcards','mind_map','quiz','tutor')
   when 'mind_map_node' then p_target in ('flashcards','quiz','tutor')
   when 'wrong_answer' then p_target in ('tutor','notes','flashcards') else false end) then
  raise exception 'Invalid conversion options' using errcode='22023';
 end if;
 if p_source->>'kind' in ('notes','mind_map_node') then
  select * into root from public.artifacts where id=source_id and user_id=p_user_id and subject_id=p_subject_id for share;
  if not found then raise exception 'Source not found' using errcode='42501'; end if;
  if root.version<>(p_source->>'version')::integer then raise exception 'Source version changed' using errcode='40001'; end if;
  if root.artifact_type<>(case when p_source->>'kind'='notes' then 'notes' else 'mind_map' end) then
   raise exception 'Source type mismatch' using errcode='22023';
  end if;
  if p_source->>'kind'='mind_map_node' and not exists(select 1 from jsonb_array_elements(root.content->'nodes') n where n->>'id'=p_source->>'nodeId') then
   raise exception 'Source node not found' using errcode='22023';
  end if;
 end if;
 task_id:=gen_random_uuid();
 insert into public.processing_tasks(id,user_id,subject_id,task_type,idempotency_key,max_attempts,metadata)
 values(task_id,p_user_id,p_subject_id,'learning_conversion','conversion:'||p_request_id,3,
  jsonb_build_object('conversionId',task_id,'target',p_target,'currentStage','queued'));
 insert into public.learning_conversions(id,user_id,subject_id,request_id,fingerprint,source_kind,
  source_material_id,source_artifact_id,source_wrong_answer_id,source_version,source_node_id,target,options,snapshot)
 values(task_id,p_user_id,p_subject_id,p_request_id,p_fingerprint,p_source->>'kind',
  case when p_source->>'kind'='material' then source_id end,
  case when p_source->>'kind' in ('notes','mind_map_node') then source_id end,
  case when p_source->>'kind'='wrong_answer' then source_id end,
  (p_source->>'version')::integer,p_source->>'nodeId',p_target,p_options,p_snapshot) returning * into saved;
 return to_jsonb(saved)-'user_id'-'claim_token';
end $$;

create function public.claim_conversion(p_id uuid) returns jsonb language plpgsql security definer set search_path=public as $$
declare job public.learning_conversions; task public.processing_tasks; token uuid;
begin
 select * into job from public.learning_conversions where id=p_id for update;
 if not found then return null; end if;
 select * into task from public.processing_tasks where id=p_id for update;
 if task.status<>'queued' and not(task.status='running' and task.started_at<now()-interval '20 minutes') then return null; end if;
 if task.attempts>=task.max_attempts then
  update public.processing_tasks set status='failed',stage='failed',error_code='retry_limit',error_message='转换重试次数已用尽' where id=p_id;
  return null;
 end if;
 token:=gen_random_uuid();
 update public.learning_conversions set claim_token=token where id=p_id returning * into job;
 update public.processing_tasks set status='running',stage='embedding',progress=20,attempts=attempts+1,
  started_at=now(),finished_at=null,error_code=null,error_message=null where id=p_id;
 return to_jsonb(job);
end $$;

create function public.transition_conversion(p_user_id uuid,p_id uuid,p_action text,p_token uuid default null,p_error text default null)
returns jsonb language plpgsql security definer set search_path=public as $$
declare job public.learning_conversions; task public.processing_tasks;
begin
 select * into job from public.learning_conversions where id=p_id and user_id=p_user_id for update;
 if not found then raise exception 'Conversion not found' using errcode='42501'; end if;
 select * into task from public.processing_tasks where id=p_id for update;
 if p_action='cancel' and task.status in ('queued','running') then
  update public.learning_conversions set claim_token=null where id=p_id;
  update public.processing_tasks set status='cancelled',stage='cancelled',finished_at=now() where id=p_id returning * into task;
 elsif p_action='retry' then
  if task.status<>'failed' or task.attempts>=task.max_attempts then raise exception 'Cannot retry conversion' using errcode='40001'; end if;
  update public.learning_conversions set claim_token=null where id=p_id;
  update public.processing_tasks set status='queued',stage='queued',progress=0,error_code=null,error_message=null,finished_at=null where id=p_id returning * into task;
 elsif p_action='fail' and task.status='running' and job.claim_token=p_token then
  update public.processing_tasks set status='failed',stage='failed',finished_at=now(),error_code='conversion_failed',
   error_message=left(coalesce(p_error,'转换失败'),1000) where id=p_id returning * into task;
 end if;
 return to_jsonb(task)-'user_id'-'idempotency_key';
end $$;

create function public.finish_conversion(p_id uuid,p_token uuid,p_draft jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
<<publish>>
declare job public.learning_conversions; task public.processing_tasks; artifact public.artifacts;
 block_ids uuid[]; canonical jsonb; provenance jsonb; topic_ids uuid[]; topic_id uuid;
 item jsonb; content jsonb; blueprint_id uuid; exam_id uuid; section_id uuid; question_id uuid; note_id uuid; count_q integer; href text; refs jsonb;
begin
 select * into job from public.learning_conversions where id=p_id for update;
 if not found then raise exception 'Conversion not found' using errcode='42501'; end if;
 select * into task from public.processing_tasks where id=p_id for update;
 if task.status='succeeded' then return to_jsonb(job)-'user_id'-'claim_token'; end if;
 if task.status<>'running' or job.claim_token is distinct from p_token then
  raise exception 'Conversion claim expired or cancelled' using errcode='40001';
 end if;
 select array_agg((value->>'id')::uuid) into block_ids from jsonb_array_elements(job.snapshot->'citations');
 canonical:=public.note_source_citations(job.user_id,job.subject_id,block_ids);
 if canonical is distinct from job.snapshot->'citations' or coalesce(jsonb_array_length(canonical),0)=0 then
  raise exception 'Source evidence changed' using errcode='40001';
 end if;
 select coalesce(array_agg(v::uuid),'{}'::uuid[]) into topic_ids from jsonb_array_elements_text(job.snapshot->'topicIds') t(v);
 if (select count(*) from public.knowledge_points where id=any(topic_ids) and user_id=job.user_id and subject_id=job.subject_id and not archived)<>cardinality(topic_ids) then
  raise exception 'Source topic unavailable' using errcode='22023';
 end if;
 provenance:=jsonb_build_object('conversionId',job.id,'sourceKind',job.source_kind,'sourceId',
  coalesce(job.source_material_id,job.source_artifact_id,job.source_wrong_answer_id),'sourceVersion',job.source_version);
 if job.target<>'tutor' then
  if coalesce(length(trim(p_draft->>'title')),0) not between 1 and 300 then raise exception 'Invalid conversion title' using errcode='22023'; end if;
  for refs in select jsonb_path_query(p_draft,'$.**.citationIds') loop
   if jsonb_typeof(refs) is distinct from 'array' or jsonb_array_length(refs)=0
     or exists(select 1 from jsonb_array_elements_text(refs) r(v) where not (v::uuid=any(block_ids))) then
    raise exception 'Invalid conversion citations' using errcode='22023';
   end if;
  end loop;
 end if;
 if job.target='tutor' then
  href:='/study-room?conversionId='||job.id;
 elsif job.target='notes' then
  note_id:=(public.save_note(job.user_id,job.subject_id,null,null,
   jsonb_build_object('title',p_draft->>'title','content',p_draft->'content','citationIds',to_jsonb(block_ids),
    'topicIds',to_jsonb(topic_ids),'mode',job.options->>'mode','modelName',p_draft->>'modelName','generationParams',provenance)) ->>'id')::uuid;
  select * into artifact from public.artifacts where id=publish.note_id;
  href:='/notes?noteId='||artifact.id;
 elsif job.target in ('flashcards','mind_map') then
  content:=p_draft->'content';
  if job.target='flashcards' then
   if jsonb_typeof(content->'cards') is distinct from 'array' or jsonb_array_length(content->'cards') not between 1 and (job.options->>'count')::integer then
    raise exception 'Invalid conversion cards' using errcode='22023';
   end if;
   content:=jsonb_set(content,'{cards}','[]'::jsonb);
   for item in select value from jsonb_array_elements(p_draft->'content'->'cards') loop
    if coalesce(length(trim(item->>'front')),0)=0 or coalesce(length(trim(item->>'back')),0)=0 or coalesce(jsonb_array_length(item->'citationIds'),0)=0 then
     raise exception 'Invalid conversion card' using errcode='22023';
    end if;
    if cardinality(topic_ids)=1 then topic_id:=topic_ids[1]; else
     topic_id:=(public.resolve_course_topic(job.user_id,job.subject_id,coalesce(item->>'knowledgeKey',item->>'front'))).id;
    end if;
    item:=item||jsonb_build_object('knowledgePointId',topic_id,'knowledgeKey',(select knowledge_key from public.knowledge_points where id=publish.topic_id));
    content:=jsonb_set(content,'{cards}',(content->'cards')||jsonb_build_array(item));
   end loop;
  end if;
  if job.target='mind_map' and (coalesce(jsonb_array_length(content->'nodes'),0)=0 or exists(select 1 from jsonb_array_elements(content->'nodes') n where coalesce(jsonb_array_length(n->'citationIds'),0)=0)) then
   raise exception 'Invalid conversion map' using errcode='22023';
  end if;
  insert into public.artifacts(user_id,subject_id,artifact_type,title,content,citations,generation_params,model_name)
   values(job.user_id,job.subject_id,job.target,p_draft->>'title',content,canonical,provenance,p_draft->>'modelName') returning * into artifact;
  insert into public.artifact_topics(artifact_id,user_id,subject_id,knowledge_point_id)
   select artifact.id,job.user_id,job.subject_id,id from unnest(topic_ids) t(id);
  if job.target='flashcards' then
   insert into public.artifact_topics(artifact_id,user_id,subject_id,knowledge_point_id)
    select distinct artifact.id,job.user_id,job.subject_id,(value->>'knowledgePointId')::uuid from jsonb_array_elements(content->'cards') on conflict do nothing;
  end if;
  href:=case when job.target='flashcards' then '/flashcards?artifactId=' else '/mind-map?artifactId=' end||artifact.id;
 elsif job.target='quiz' then
  count_q:=(job.options->>'count')::integer;
  if jsonb_typeof(p_draft->'questions') is distinct from 'array' or jsonb_array_length(p_draft->'questions')<>count_q then
   raise exception 'Invalid conversion question count' using errcode='22023';
  end if;
  insert into public.exam_blueprints(user_id,subject_id,title,duration_minutes,total_points,specification)
   values(job.user_id,job.subject_id,p_draft->>'title',30,count_q*5,
    jsonb_build_object('knowledgePolicy','course_only','assessmentType','practice','retrieval',provenance||jsonb_build_object('externalUsed',false),
     'evidence',canonical,'questionTypes',jsonb_build_array(jsonb_build_object('questionType','single_choice','count',count_q,'pointsEach',5)))) returning id into blueprint_id;
  insert into public.exams(user_id,subject_id,blueprint_id,title,duration_minutes,total_points,assessment_mode)
   values(job.user_id,job.subject_id,publish.blueprint_id,p_draft->>'title',30,count_q*5,'adaptive') returning id into exam_id;
  insert into public.exam_sections(exam_id,title,sequence_index,points) values(publish.exam_id,'转换测验',0,count_q*5) returning id into section_id;
  count_q:=0;
  for item in select value from jsonb_array_elements(p_draft->'questions') loop
   if item->>'questionType' is distinct from 'single_choice'
     or coalesce(jsonb_array_length(item->'options'),0)<2
     or coalesce(jsonb_array_length(item->'citationIds'),0)=0
     or coalesce(length(trim(item->>'stem')),0)=0 or coalesce(length(trim(item->>'explanation')),0)=0
     or not (case jsonb_typeof(item->'correctAnswer')
       when 'string' then item->'options' @> jsonb_build_array(item->'correctAnswer')
       when 'array' then jsonb_array_length(item->'correctAnswer')=1 and item->'options' @> (item->'correctAnswer') else false end) then
    raise exception 'Invalid conversion question' using errcode='22023';
   end if;
   if cardinality(topic_ids)=1 then topic_id:=topic_ids[1]; else
    topic_id:=(public.resolve_course_topic(job.user_id,job.subject_id,coalesce(item->>'knowledgeKey','未分类'))).id;
   end if;
   insert into public.questions(user_id,subject_id,question_type,knowledge_key,knowledge_point_id,difficulty,source_kind)
    values(job.user_id,job.subject_id,'single_choice',(select knowledge_key from public.knowledge_points where id=publish.topic_id),publish.topic_id,'medium','material') returning id into question_id;
   insert into public.question_versions(question_id,version,stem,options,correct_answer,explanation,citations,quality)
    values(publish.question_id,1,item->>'stem',item->'options',item->'correctAnswer',item->>'explanation',item->'citationIds',jsonb_build_object('validated',true));
   insert into public.exam_questions(exam_id,section_id,question_id,question_version,sequence_index,points)
    values(publish.exam_id,publish.section_id,publish.question_id,1,count_q,5);
   count_q:=count_q+1;
  end loop;
  href:='/exams?examId='||exam_id;
 end if;
 update public.learning_conversions set result_artifact_id=artifact.id,result_exam_id=publish.exam_id,result_href=href where id=p_id returning * into job;
 update public.processing_tasks set status='succeeded',stage='ready',progress=100,finished_at=now(),
  metadata=metadata||jsonb_build_object('currentStage','ready','artifactId',artifact.id,'examId',exam_id,'resultHref',href) where id=p_id;
 return to_jsonb(job)-'user_id'-'claim_token';
end $$;

create function public.cancel_deleted_conversion() returns trigger language plpgsql security definer set search_path=public as $$
begin
 update public.processing_tasks set status='cancelled',stage='cancelled',finished_at=now(),error_message='学习来源或结果已删除'
 where id=old.id and status in ('queued','running');
 return old;
end $$;
create trigger cancel_deleted_conversion after delete on public.learning_conversions for each row execute function public.cancel_deleted_conversion();
revoke all on function public.cancel_deleted_conversion() from public,anon,authenticated;

revoke all on function public.enqueue_conversion(uuid,uuid,uuid,text,jsonb,text,jsonb,jsonb),public.claim_conversion(uuid),
 public.transition_conversion(uuid,uuid,text,uuid,text),public.finish_conversion(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.enqueue_conversion(uuid,uuid,uuid,text,jsonb,text,jsonb,jsonb),public.claim_conversion(uuid),
 public.transition_conversion(uuid,uuid,text,uuid,text),public.finish_conversion(uuid,uuid,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
