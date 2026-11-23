begin;
alter table public.materials
 add column upload_notes_mode text,
 add column upload_notes_request_id uuid,
 add column upload_notes_dispatched boolean not null default false,
 add column upload_notes_attempts integer not null default 0,
 add column upload_notes_error text,
 add column upload_notes_retry_at timestamptz,
 add constraint materials_upload_notes_check check (
   (upload_notes_mode is null)=(upload_notes_request_id is null)
   and (upload_notes_mode is null or upload_notes_mode in ('summary','standard','comprehensive','exam_focus'))),
 add constraint materials_upload_notes_attempts check(upload_notes_attempts between 0 and 3);
create unique index material_upload_notes_request_unique on public.materials(user_id,upload_notes_request_id)
 where upload_notes_request_id is not null;

-- A committed conversion acknowledges its upload intent in the same transaction.
-- Deleting a result later must never re-enrol the material for automatic generation.
create function public.ack_upload_notes_conversion() returns trigger
language plpgsql security definer set search_path=public as $$
begin
 if new.source_kind='material' and new.target='notes' then
   update materials set upload_notes_dispatched=true,upload_notes_error=null,upload_notes_retry_at=null
     where id=new.source_material_id and user_id=new.user_id and subject_id=new.subject_id
       and upload_notes_request_id=new.request_id and upload_notes_mode=new.options->>'mode'
       and new.options->>'count'='10';
 end if;
 return new;
end $$;
revoke all on function public.ack_upload_notes_conversion() from public,anon,authenticated;
create trigger acknowledge_upload_notes after insert on public.learning_conversions
 for each row execute function public.ack_upload_notes_conversion();

create function public.configure_upload_notes(p_user uuid,p_material uuid,p_mode text) returns jsonb
language plpgsql security definer set search_path=public as $$
declare mat materials;
begin
 select * into mat from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material not found' using errcode='42501'; end if;
 if p_mode is null or p_mode not in ('summary','standard','comprehensive','exam_focus') then
   raise exception 'Invalid mode' using errcode='22023'; end if;
 if mat.upload_notes_mode is not null and mat.upload_notes_mode<>p_mode then
   raise exception 'Upload Notes already configured with another mode' using errcode='40001'; end if;
 if mat.upload_notes_mode is null then
   update materials set upload_notes_mode=p_mode,upload_notes_request_id=gen_random_uuid()
     where id=p_material returning * into mat;
 end if;
 return to_jsonb(mat);
end $$;

create function public.transition_upload_notes(p_user uuid,p_material uuid,p_action text,p_conversion uuid default null) returns jsonb
language plpgsql security definer set search_path=public as $$
declare mat materials;
begin
 select * into mat from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material not found' using errcode='42501'; end if;
 if mat.upload_notes_mode is null then raise exception 'Notes not requested' using errcode='22023'; end if;
 if p_action='start' then
   if mat.status<>'ready' or mat.upload_notes_dispatched or mat.upload_notes_attempts>=3
     or mat.upload_notes_retry_at>now() then return null; end if;
   update materials set upload_notes_attempts=upload_notes_attempts+1,upload_notes_error=null,
     upload_notes_retry_at=now()+interval '1 minute' where id=p_material returning * into mat;
 elsif p_action='done' then
   if not exists(select 1 from learning_conversions c where c.id=p_conversion and c.user_id=p_user
     and c.subject_id=mat.subject_id and c.request_id=mat.upload_notes_request_id
     and c.source_kind='material' and c.source_material_id=mat.id and c.target='notes'
     and c.options->>'mode'=mat.upload_notes_mode and c.options->>'count'='10') then
     raise exception 'Conversion mismatch' using errcode='22023'; end if;
   update materials set upload_notes_dispatched=true,upload_notes_error=null,upload_notes_retry_at=null
     where id=p_material returning * into mat;
 elsif p_action='error' then
   if not mat.upload_notes_dispatched then
     update materials set upload_notes_error='笔记任务暂未创建，可稍后重试'
       where id=p_material returning * into mat;
   end if;
 elsif p_action='reset' then
   if mat.upload_notes_dispatched or mat.status<>'ready'
      or (mat.upload_notes_error is null and mat.upload_notes_retry_at>now()) then
     raise exception 'Notes already dispatched or preparing' using errcode='40001'; end if;
   update materials set upload_notes_attempts=0,upload_notes_retry_at=null,upload_notes_error=null
     where id=p_material returning * into mat;
 else raise exception 'Invalid transition' using errcode='22023'; end if;
 return to_jsonb(mat);
end $$;

create function public.pending_upload_notes() returns jsonb
language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(to_jsonb(m)),'[]'::jsonb) from (
   select id,user_id,subject_id from materials where status='ready' and upload_notes_mode is not null
     and not upload_notes_dispatched and upload_notes_attempts<3
     and (upload_notes_retry_at is null or upload_notes_retry_at<=now())
   order by created_at,id limit 20
 ) m
$$;

-- Extend the existing bulk status response without one query per material.
create or replace function public.material_processing_summary(p_user uuid,p_subject uuid)
returns jsonb language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(jsonb_build_object(
   'materialId',m.id,'task',to_jsonb(t),
   'sourceAvailable',exists(select 1 from material_assets a where a.material_id=m.id
     and a.user_id=p_user and a.subject_id=p_subject and a.asset_type='original'
     and (a.expires_at is null or a.expires_at>now())),
   'notes',case when m.upload_notes_mode is null then null else jsonb_build_object(
     'mode',m.upload_notes_mode,'conversionId',c.id,'href',c.result_href,
     'status',case when c.id is not null then nt.status
       when m.upload_notes_dispatched then 'removed'
       when m.status<>'ready' then 'waiting_material'
       when m.upload_notes_error is not null or (m.upload_notes_attempts>=3 and m.upload_notes_retry_at<=now()) then 'enqueue_failed' else 'pending' end,
     'error',coalesce(nt.error_message,m.upload_notes_error),'attempts',m.upload_notes_attempts,
     'warnings',coalesce(c.snapshot->'warnings','[]'::jsonb),
     'canRetry',case when c.id is not null then nt.status='failed' and nt.attempts<nt.max_attempts
       else not m.upload_notes_dispatched and m.status='ready' and (m.upload_notes_error is not null
         or (m.upload_notes_attempts>=3 and m.upload_notes_retry_at<=now())) end
   ) end
 ) order by m.created_at desc,m.id),'[]'::jsonb)
 from materials m left join lateral (
   select t.* from processing_tasks t where t.user_id=p_user and t.subject_id=p_subject
     and t.material_id=m.id and t.task_type='material_ingestion'
   order by t.created_at desc,t.id desc limit 1
 ) t on true left join learning_conversions c on c.user_id=p_user and c.subject_id=p_subject
   and c.request_id=m.upload_notes_request_id
 left join processing_tasks nt on nt.id=c.id and nt.user_id=p_user and nt.subject_id=p_subject
 where m.user_id=p_user and m.subject_id=p_subject
   and exists(select 1 from subjects s where s.id=p_subject and s.user_id=p_user)
$$;

revoke all on function public.configure_upload_notes(uuid,uuid,text),
 public.transition_upload_notes(uuid,uuid,text,uuid),public.pending_upload_notes() from public,anon,authenticated;
grant execute on function public.configure_upload_notes(uuid,uuid,text),
 public.transition_upload_notes(uuid,uuid,text,uuid),public.pending_upload_notes() to service_role;
notify pgrst,'reload schema';
commit;
