-- Classification is descriptive: syllabus does not silently create exams/Topics.
alter table public.materials add column if not exists material_purpose text not null default 'learning';
alter table public.materials add constraint materials_purpose_check
    check (material_purpose in ('learning','syllabus','reference'));

create index if not exists material_ingestion_latest_idx
    on public.processing_tasks(user_id,material_id,created_at desc,id desc)
    where task_type='material_ingestion';

create function public.material_processing_summary(p_user uuid,p_subject uuid)
returns jsonb language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(jsonb_build_object(
   'materialId',m.id,'task',to_jsonb(t),
   'sourceAvailable',exists(select 1 from material_assets a
     where a.material_id=m.id and a.user_id=p_user and a.subject_id=p_subject
       and a.asset_type='original' and (a.expires_at is null or a.expires_at>now()))
 ) order by m.created_at desc,m.id),'[]'::jsonb)
 from materials m left join lateral (
   select t.* from processing_tasks t where t.user_id=p_user and t.subject_id=p_subject
     and t.material_id=m.id and t.task_type='material_ingestion'
   order by t.created_at desc,t.id desc limit 1
 ) t on true where m.user_id=p_user and m.subject_id=p_subject
   and exists(select 1 from subjects s where s.id=p_subject and s.user_id=p_user)
$$;

create function public.retry_material_ingestion(p_user uuid,p_task uuid)
returns jsonb language plpgsql security definer set search_path=public as $$
declare job processing_tasks; mat materials;
begin
 select * into job from processing_tasks where id=p_task and user_id=p_user for update;
 if not found then raise exception 'Task not found' using errcode='42501'; end if;
 if job.task_type<>'material_ingestion' or job.status<>'failed' then
   raise exception 'Only failed ingestion tasks can be retried' using errcode='40001';
 end if;
 select * into mat from materials where id=job.material_id and user_id=p_user
   and subject_id=job.subject_id for update;
 if not found then raise exception 'Material not found' using errcode='42501'; end if;
 if mat.status<>'failed' or exists(select 1 from processing_tasks t
   where t.material_id=mat.id and t.user_id=p_user and t.id<>job.id
     and t.task_type='material_ingestion' and t.status in ('queued','running')) then
   raise exception 'Material already processing or complete' using errcode='40001';
 end if;
 if not exists(select 1 from material_assets a where a.material_id=mat.id
   and a.user_id=p_user and a.subject_id=job.subject_id and a.asset_type='original'
   and (a.expires_at is null or a.expires_at>now())) then
   raise exception 'Original file unavailable; upload the file again' using errcode='22023';
 end if;
 -- Manual retry starts a fresh bounded cycle; retain the previous attempt count.
 update processing_tasks set status='queued',stage='queued',progress=0,attempts=0,
   error_code=null,error_message=null,started_at=null,finished_at=null,
   metadata=metadata||jsonb_build_object('previousAttempts',job.attempts,
     'manualRetryCount',coalesce((metadata->>'manualRetryCount')::int,0)+1)
   where id=job.id returning * into job;
 update materials set status='queued',error_message=null where id=mat.id;
 return to_jsonb(job);
end $$;

revoke all on function public.material_processing_summary(uuid,uuid) from public,anon,authenticated;
revoke all on function public.retry_material_ingestion(uuid,uuid) from public,anon,authenticated;
grant execute on function public.material_processing_summary(uuid,uuid) to service_role;
grant execute on function public.retry_material_ingestion(uuid,uuid) to service_role;

create function public.fail_material_dispatch(p_user uuid,p_task uuid)
returns jsonb language plpgsql security definer set search_path=public as $$
declare job processing_tasks;
begin
 select * into job from processing_tasks where id=p_task and user_id=p_user for update;
 if not found or job.task_type<>'material_ingestion' then
   raise exception 'Task not found' using errcode='42501';
 end if;
 -- A lost broker acknowledgement can coexist with an already started worker.
 if job.status='queued' then
   update processing_tasks set status='failed',stage='failed',error_code='dispatch_failed',
     error_message='任务服务暂时不可用，请稍后重试',finished_at=now(),
     metadata=metadata||jsonb_build_object('failedStage','queued')
     where id=p_task returning * into job;
   update materials set status='failed',error_message=job.error_message
     where id=job.material_id and user_id=p_user and status='queued';
 end if;
 return to_jsonb(job);
end $$;
revoke all on function public.fail_material_dispatch(uuid,uuid) from public,anon,authenticated;
grant execute on function public.fail_material_dispatch(uuid,uuid) to service_role;
notify pgrst,'reload schema';
