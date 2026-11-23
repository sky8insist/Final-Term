begin;
create table public.daily_review_schedules (
 user_id uuid not null,subject_id uuid not null,enabled boolean not null default false,hour integer not null default 22 check(hour between 0 and 23),
 version integer not null default 1,primary key(user_id,subject_id),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create table public.learning_job_outbox (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,
 kind text not null check(kind in ('daily_review','projection_refresh')),day date not null,
 source_id uuid,status text not null default 'queued' check(status in ('queued','running','succeeded','dead')),
 attempts integer not null default 0,max_attempts integer not null default 5,
 available_at timestamptz not null default now(),lease_until timestamptz,claim_token uuid,
 error_code text,result_id uuid,created_at timestamptz not null default now(),
 foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
create unique index daily_review_job_once on public.learning_job_outbox(user_id,subject_id,day) where kind='daily_review';
create index learning_job_ready on public.learning_job_outbox(status,available_at,lease_until);
do $$ declare tab text; begin
 foreach tab in array array['daily_review_schedules','learning_job_outbox'] loop
 execute format('alter table public.%I enable row level security',tab);
 execute format('create policy "Read own %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
 execute format('revoke all on public.%I from public,anon,authenticated',tab);
 execute format('grant select on public.%I to authenticated',tab);
 execute format('grant all on public.%I to service_role',tab);
 end loop;
end $$;

create function public.save_daily_review_schedule(p_user uuid,p_subject uuid,p_enabled boolean,p_hour integer,p_version integer) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved daily_review_schedules;
begin
 if not exists(select 1 from subjects where id=p_subject and user_id=p_user) then raise exception 'Subject unavailable' using errcode='42501'; end if;
 perform pg_advisory_xact_lock(hashtextextended('daily-schedule:'||p_user::text||p_subject::text,0));
 select * into saved from daily_review_schedules where user_id=p_user and subject_id=p_subject;
 if coalesce(saved.version,0)<>p_version then raise exception 'Schedule changed' using errcode='40001'; end if;
 insert into daily_review_schedules(user_id,subject_id,enabled,hour) values(p_user,p_subject,p_enabled,p_hour)
 on conflict(user_id,subject_id) do update set enabled=excluded.enabled,hour=excluded.hour,version=daily_review_schedules.version+1 returning * into saved;
 if not p_enabled then
  update learning_job_outbox set status='dead',error_code='schedule_disabled',claim_token=null,lease_until=null
   where user_id=p_user and subject_id=p_subject and kind='daily_review' and status in ('queued','running');
 end if;
 return to_jsonb(saved)-'user_id';
end $$;

create function public.enqueue_daily_review_jobs() returns integer language plpgsql security definer set search_path=public as $$
declare inserted integer;
begin
 insert into learning_job_outbox(user_id,subject_id,kind,day)
 select user_id,subject_id,'daily_review',(now() at time zone 'Asia/Shanghai')::date from daily_review_schedules
 where enabled and hour<=extract(hour from now() at time zone 'Asia/Shanghai') on conflict do nothing;
 get diagnostics inserted=row_count;
 return inserted;
end $$;

create function public.claim_learning_job(p_job uuid) returns jsonb language plpgsql security definer set search_path=public as $$
declare job learning_job_outbox;
begin
 select * into job from learning_job_outbox where id=p_job for update skip locked;
 if not found or job.status not in ('queued','running') then return null; end if;
 if job.kind='daily_review' and job.day<>(now() at time zone 'Asia/Shanghai')::date then
  update learning_job_outbox set status='dead',error_code='day_expired',claim_token=null,lease_until=null where id=p_job;return null;end if;
 if job.attempts>=job.max_attempts then
  if job.status='queued' or job.lease_until<=now() then update learning_job_outbox set status='dead',error_code='attempts_exhausted' where id=p_job;end if;
  return null;
 end if;
 if job.available_at>now() or (job.status='running' and job.lease_until>now()) then return null; end if;
 update learning_job_outbox set status='running',attempts=attempts+1,claim_token=gen_random_uuid(),lease_until=now()+interval '2 minutes'
 where id=p_job returning * into job;
 return to_jsonb(job);
end $$;

create function public.finish_learning_job(p_job uuid,p_token uuid,p_error text default null,p_result uuid default null) returns boolean
language plpgsql security definer set search_path=public as $$
declare job learning_job_outbox;
begin
 select * into job from learning_job_outbox where id=p_job and status='running' and claim_token=p_token and lease_until>now() for update;
 if not found then return false;end if;
 update learning_job_outbox set status=case when p_error is null then 'succeeded' when attempts>=max_attempts then 'dead' else 'queued' end,
 available_at=now()+make_interval(secs=>least(300,attempts*30)),error_code=left(p_error,80),result_id=p_result,
 claim_token=null,lease_until=null where id=p_job;
 return true;
end $$;

create function public.ready_learning_jobs() returns jsonb language sql stable security definer set search_path=public as $$
 select coalesce(jsonb_agg(id),'[]') from (select id from learning_job_outbox where (status='queued' and available_at<=now())
 or (status='running' and lease_until<=now()) order by available_at,id limit 50) q
$$;

-- Automated publication checks the current lease and schedule in the same transaction.
create function public.publish_daily_review_job(p_job uuid,p_token uuid,p_source jsonb,p_report jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare job learning_job_outbox;saved jsonb;
begin
 select * into job from learning_job_outbox where id=p_job;
 if not found then raise exception 'Job unavailable' using errcode='42501';end if;
 perform pg_advisory_xact_lock(hashtextextended('daily-schedule:'||job.user_id::text||job.subject_id::text,0));
 select * into job from learning_job_outbox where id=p_job for update;
 if job.status<>'running' or job.claim_token is distinct from p_token or job.lease_until<=now() then raise exception 'Lease changed' using errcode='40001';end if;
 if job.kind<>'daily_review' or not exists(select 1 from daily_review_schedules where user_id=job.user_id and subject_id=job.subject_id and enabled for share) then
  raise exception 'Schedule disabled' using errcode='40001';end if;
 saved:=save_daily_learning_review(job.user_id,job.subject_id,job.day,job.id,p_source,p_report);
 perform finish_learning_job(p_job,p_token,null,(saved->>'id')::uuid);
 return saved;
end $$;
revoke all on function public.save_daily_review_schedule(uuid,uuid,boolean,integer,integer),public.enqueue_daily_review_jobs(),public.claim_learning_job(uuid),public.finish_learning_job(uuid,uuid,text,uuid),public.ready_learning_jobs(),public.publish_daily_review_job(uuid,uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.save_daily_review_schedule(uuid,uuid,boolean,integer,integer),public.enqueue_daily_review_jobs(),public.claim_learning_job(uuid),public.finish_learning_job(uuid,uuid,text,uuid),public.ready_learning_jobs(),public.publish_daily_review_job(uuid,uuid,jsonb,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
