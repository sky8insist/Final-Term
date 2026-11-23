begin;
-- The task row is also the durable outbox: committed queued rows are swept
-- until a worker claims them. Broker acknowledgement is never authoritative.
alter table processing_tasks add column ingestion_token uuid;
alter table processing_tasks add column ingestion_lease_until timestamptz;
alter table processing_tasks add column ingestion_available_at timestamptz not null default now();
create index ingestion_due on processing_tasks(ingestion_available_at,id) where task_type='material_ingestion' and status in ('queued','running');
create table material_ingestion_checkpoints (
 task_id uuid not null references processing_tasks(id) on delete cascade,
 user_id uuid not null,subject_id uuid not null,stage text not null check(stage in ('parsed','embedded')),
 pipeline_version text not null,payload jsonb not null,created_at timestamptz not null default now(),
 primary key(task_id,stage),foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
alter table material_ingestion_checkpoints enable row level security;
revoke all on material_ingestion_checkpoints from public,anon,authenticated;
grant select,delete on material_ingestion_checkpoints to service_role;
create function discard_ingestion_source_checkpoints() returns trigger
language plpgsql security definer set search_path=public as $$
begin
 if old.asset_type='original' then
  delete from material_ingestion_checkpoints c using processing_tasks t
   where c.task_id=t.id and t.material_id=old.material_id and t.user_id=old.user_id;
 end if;
 return null;
end $$;
create trigger discard_ingestion_source_checkpoints after delete on material_assets
 for each row execute function discard_ingestion_source_checkpoints();

create function register_material_upload(p_user uuid,p_material uuid,p_asset jsonb,p_metadata jsonb,p_attempts integer)
returns jsonb language plpgsql security definer set search_path=public as $$
declare m materials;j processing_tasks;
begin
 select * into m from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material unavailable' using errcode='42501';end if;
 if m.status<>'queued' or p_attempts not between 1 and 10 or p_asset->>'sha256'<>m.source_hash
 or split_part(p_asset->>'object_path','/',1)<>p_user::text then raise exception 'Invalid upload' using errcode='22023';end if;
 insert into material_assets(user_id,subject_id,material_id,asset_type,bucket,object_path,content_type,file_size,sha256,expires_at)
 values(p_user,m.subject_id,m.id,'original',p_asset->>'bucket',p_asset->>'object_path',m.content_type,m.file_size,m.source_hash,(p_asset->>'expires_at')::timestamptz)
 on conflict(bucket,object_path) do nothing;
 insert into processing_tasks(user_id,subject_id,material_id,idempotency_key,max_attempts,metadata)
 values(p_user,m.subject_id,m.id,'material:'||m.id||':'||m.source_hash,p_attempts,coalesce(p_metadata,'{}'))
 on conflict(user_id,idempotency_key) do update set metadata=processing_tasks.metadata returning * into j;
 return to_jsonb(j);
end $$;
create function ready_material_ingestions(p_limit integer default 50,p_user uuid default null) returns jsonb
language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(id),'[]') from (select id from processing_tasks where task_type='material_ingestion'
 and (p_user is null or user_id=p_user) and ingestion_available_at<=now()
 and (status='queued' or (status='running' and coalesce(ingestion_lease_until,'-infinity')<=now()))
 order by ingestion_available_at,id limit least(greatest(p_limit,1),100)) q
$$;
create function claim_material_ingestion(p_task uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare j processing_tasks;
begin
 select * into j from processing_tasks where id=p_task for update skip locked;
 if not found or j.task_type<>'material_ingestion' or j.status not in ('queued','running')
 or j.ingestion_available_at>now() or (j.status='running' and j.ingestion_lease_until>now()) then return null;end if;
 if j.attempts>=j.max_attempts then
  update processing_tasks set status='failed',stage='failed',ingestion_token=null,ingestion_lease_until=null,
   error_code='attempts_exhausted',error_message='处理重试次数已耗尽，请手动重试',finished_at=now() where id=j.id;
  update materials set status='failed',error_message='处理重试次数已耗尽，请手动重试' where id=j.material_id;
  return null;
 end if;
 update processing_tasks set status='running',stage='parsing',attempts=attempts+1,ingestion_token=gen_random_uuid(),
  ingestion_lease_until=now()+interval '2 minutes',started_at=coalesce(started_at,now()),error_code=null,error_message=null
 where id=j.id returning * into j;
 update materials set status='parsing',error_message=null where id=j.material_id and user_id=j.user_id;
 return to_jsonb(j);
end $$;
create function touch_material_ingestion(p_task uuid,p_token uuid,p_stage text default null,p_metadata jsonb default null)
returns boolean language plpgsql security definer set search_path=public as $$
begin
 if p_stage is not null and p_stage not in ('parsing','embedding','indexing') then raise exception 'Invalid stage' using errcode='22023';end if;
 update processing_tasks set ingestion_lease_until=now()+interval '2 minutes',stage=coalesce(p_stage,stage),
  metadata=metadata||coalesce(p_metadata,'{}'),progress=case p_stage when 'parsing' then 15 when 'embedding' then 45 when 'indexing' then 75 else progress end
 where id=p_task and status='running' and ingestion_token=p_token and ingestion_lease_until>now();
 return found;
end $$;
create function save_material_checkpoint(p_task uuid,p_token uuid,p_stage text,p_version text,p_payload jsonb)
returns void language plpgsql security definer set search_path=public as $$
declare j processing_tasks;
begin
 select * into j from processing_tasks where id=p_task and status='running' and ingestion_token=p_token and ingestion_lease_until>now() for update;
 if not found then raise exception 'Lease changed' using errcode='40001';end if;
 if octet_length(p_payload::text)>20971520 then raise exception 'Checkpoint exceeds 20MiB' using errcode='22023';end if;
 insert into material_ingestion_checkpoints(task_id,user_id,subject_id,stage,pipeline_version,payload)
 values(j.id,j.user_id,j.subject_id,p_stage,p_version,p_payload)
 on conflict(task_id,stage) do update set pipeline_version=excluded.pipeline_version,payload=excluded.payload,created_at=now();
end $$;
create function fail_material_ingestion(p_task uuid,p_token uuid,p_error text) returns boolean
language plpgsql security definer set search_path=public as $$
declare j processing_tasks;terminal boolean;
begin
 select * into j from processing_tasks where id=p_task and status='running' and ingestion_token=p_token and ingestion_lease_until>now() for update;
 if not found then return false;end if;
 terminal:=j.attempts>=j.max_attempts;
 update processing_tasks set status=case when terminal then 'failed' else 'queued' end,stage=case when terminal then 'failed' else 'queued' end,
  error_code='processing_failed',error_message=left(p_error,80),ingestion_token=null,ingestion_lease_until=null,
  metadata=metadata||jsonb_build_object('failedStage',j.stage),
  ingestion_available_at=now()+make_interval(secs=>least(300,30*j.attempts)),finished_at=case when terminal then now() else null end where id=j.id;
 update materials set status=case when terminal then 'failed' else 'queued' end,error_message='资料处理暂未完成，可稍后重试' where id=j.material_id;
 return true;
end $$;
create function cancel_material_ingestion(p_user uuid,p_task uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare j processing_tasks;
begin
 select * into j from processing_tasks where id=p_task and user_id=p_user and task_type='material_ingestion' for update;
 if not found then raise exception 'Task unavailable' using errcode='42501';end if;
 if j.status in ('queued','running') then
  update processing_tasks set status='cancelled',stage='cancelled',ingestion_token=null,ingestion_lease_until=null,finished_at=now() where id=j.id returning * into j;
  update materials set status='failed',error_message='处理已取消' where id=j.material_id;
 end if;
 return to_jsonb(j);
end $$;

create function publish_material_ingestion(p_task uuid,p_token uuid,p_version text,p_graph_status text,p_workspace text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare j processing_tasks;bundle jsonb;parsed jsonb;b jsonb;chunks jsonb;c jsonb;vec jsonb;
begin
 select * into j from processing_tasks where id=p_task and status='running' and ingestion_token=p_token and ingestion_lease_until>now() for update;
 if not found then raise exception 'Lease changed' using errcode='40001';end if;
 perform 1 from materials where id=j.material_id and user_id=j.user_id and subject_id=j.subject_id for update;
 if not found then raise exception 'Material unavailable' using errcode='42501';end if;
 select payload into parsed from material_ingestion_checkpoints where task_id=j.id and stage='parsed' and pipeline_version=p_version;
 select payload into bundle from material_ingestion_checkpoints where task_id=j.id and stage='embedded' and pipeline_version=p_version;
 if parsed is null or bundle is null or p_graph_status not in ('indexed','failed') then raise exception 'Incomplete checkpoints' using errcode='22023';end if;
 for b in select value from jsonb_array_elements(parsed->'blocks') loop
  insert into content_blocks(id,user_id,subject_id,material_id,block_type,content_text,structured_data,page_number,bounding_box,
   start_time,end_time,sequence_index,parser_name,parser_version,confidence,source_hash,metadata)
  values((b->>'id')::uuid,j.user_id,j.subject_id,j.material_id,b->>'block_type',b->>'content_text',coalesce(b->'structured_data','{}'),
   (b->>'page_number')::integer,b->'bounding_box',(b->>'start_time')::double precision,(b->>'end_time')::double precision,
   (b->>'sequence_index')::integer,b->>'parser_name',b->>'parser_version',(b->>'confidence')::double precision,b->>'source_hash',coalesce(b->'metadata','{}'))
  on conflict(id) do update set content_text=excluded.content_text,structured_data=excluded.structured_data,
   metadata=excluded.metadata,page_number=excluded.page_number,bounding_box=excluded.bounding_box,
   start_time=excluded.start_time,end_time=excluded.end_time,confidence=excluded.confidence
   where content_blocks.user_id=j.user_id and content_blocks.subject_id=j.subject_id and content_blocks.material_id=j.material_id;
  if not found then raise exception 'Block scope changed' using errcode='42501';end if;
  if coalesce((b->'metadata'->'promptInjectionRisk'->>'suspicious')::boolean,false) then
   insert into security_events(user_id,material_id,event_type,severity,details)
   values(j.user_id,j.material_id,'uploaded_prompt_injection',b->'metadata'->'promptInjectionRisk'->>'severity',
    jsonb_build_object('sourceHash',b->>'source_hash','matchedPatterns',b->'metadata'->'promptInjectionRisk'->'matchedPatterns'));
  end if;
 end loop;
 chunks:=replace_material_chunk_bundle(j.user_id,j.subject_id,j.material_id,bundle->>'strategy',bundle->'parents',bundle->'records');
 if jsonb_array_length(chunks)<>jsonb_array_length(bundle->'vectors') or jsonb_array_length(chunks)=0 then raise exception 'Vector count mismatch' using errcode='22023';end if;
 for c in select value from jsonb_array_elements(chunks) loop
  vec:=bundle->'vectors'->((c->>'chunk_index')::integer);
  if jsonb_array_length(vec)=0 or jsonb_array_length(vec)<>jsonb_array_length(bundle->'vectors'->0) then
   raise exception 'Vector dimensions mismatch' using errcode='22023';end if;
  update material_chunks set embedding=vec::text::vector,embedding_model=bundle->>'model',embedding_dimensions=jsonb_array_length(vec),embedded_at=now()
   where id=(c->>'id')::uuid and user_id=j.user_id and material_id=j.material_id;
 end loop;
 insert into lightrag_material_index(user_id,subject_id,material_id,workspace,status,indexed_at,error_message)
 values(j.user_id,j.subject_id,j.material_id,p_workspace,p_graph_status,case when p_graph_status='indexed' then now() else null end,
  case when p_graph_status='failed' then 'Optional graph indexing unavailable' else null end)
 on conflict(user_id,material_id) do update set status=excluded.status,workspace=excluded.workspace,indexed_at=excluded.indexed_at,error_message=excluded.error_message;
 update materials set status='ready',error_message=null where id=j.material_id;
 update processing_tasks set status='succeeded',stage='ready',progress=100,finished_at=now(),ingestion_token=null,ingestion_lease_until=null,
  error_code=null,error_message=null where id=j.id;
 -- Completed tasks are the dedupe receipt. Large payloads need not persist.
 delete from material_ingestion_checkpoints where task_id=j.id;
 return jsonb_build_object('status','ready','materialId',j.material_id);
end $$;

-- Preserve 046's ownership/source/manual retry rules, plus release old leases.
alter function retry_material_ingestion(uuid,uuid) rename to retry_material_ingestion_046;
create function retry_material_ingestion(p_user uuid,p_task uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare result jsonb;
begin
 result:=retry_material_ingestion_046(p_user,p_task);
 update processing_tasks set ingestion_token=null,ingestion_lease_until=null,ingestion_available_at=now() where id=p_task;
 return result;
end $$;
-- No broker failure is terminal: the committed outbox remains sweepable.
create or replace function fail_material_dispatch(p_user uuid,p_task uuid) returns jsonb
language plpgsql security definer set search_path=public as $$
declare j processing_tasks;
begin
 select * into j from processing_tasks where id=p_task and user_id=p_user and task_type='material_ingestion' for update;
 if not found then raise exception 'Task unavailable' using errcode='42501';end if;
 if j.status='queued' then update processing_tasks set error_code='dispatch_pending',error_message='任务已保存，等待自动投递' where id=j.id returning * into j;end if;
 return to_jsonb(j);
end $$;
revoke all on function retry_material_ingestion_046(uuid,uuid) from service_role;
revoke all on function discard_ingestion_source_checkpoints() from public,anon,authenticated;
revoke all on function register_material_upload(uuid,uuid,jsonb,jsonb,integer),ready_material_ingestions(integer,uuid),claim_material_ingestion(uuid),
 touch_material_ingestion(uuid,uuid,text,jsonb),save_material_checkpoint(uuid,uuid,text,text,jsonb),fail_material_ingestion(uuid,uuid,text),
 cancel_material_ingestion(uuid,uuid),publish_material_ingestion(uuid,uuid,text,text,text),retry_material_ingestion(uuid,uuid) from public,anon,authenticated;
grant execute on function register_material_upload(uuid,uuid,jsonb,jsonb,integer),ready_material_ingestions(integer,uuid),claim_material_ingestion(uuid),
 touch_material_ingestion(uuid,uuid,text,jsonb),save_material_checkpoint(uuid,uuid,text,text,jsonb),fail_material_ingestion(uuid,uuid,text),
 cancel_material_ingestion(uuid,uuid),publish_material_ingestion(uuid,uuid,text,text,text),retry_material_ingestion(uuid,uuid) to service_role;
notify pgrst,'reload schema';
commit;
