begin;
-- Record the destination BEFORE Storage IO. A crashed uploader leaves durable
-- cleanup work even when no material_assets manifest was committed.
create table material_upload_intents (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 subject_id uuid references subjects(id) on delete set null,
 material_id uuid references materials(id) on delete set null,
 bucket text not null,object_path text not null,source_hash text not null,
 status text not null default 'pending' check(status in ('pending','registered','cleaning','cleaned')),
 created_at timestamptz not null default now(),attempts integer not null default 0,
 claim_token uuid,lease_until timestamptz,retry_at timestamptz,error_code text,
 unique(bucket,object_path)
);
create index upload_intent_due on material_upload_intents(created_at,id) where status in ('pending','cleaning');
create index upload_intent_owner on material_upload_intents(user_id,subject_id);
alter table material_upload_intents enable row level security;
revoke all on material_upload_intents from public,anon,authenticated;
grant select,delete on material_upload_intents to service_role;

create function prepare_material_upload(p_user uuid,p_material uuid,p_bucket text,p_path text,p_hash text) returns uuid
language plpgsql security definer set search_path=public as $$
declare m materials;item material_upload_intents;
begin
 select * into m from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material unavailable' using errcode='42501';end if;
 if m.status<>'queued' or p_hash is distinct from m.source_hash or p_bucket is null or p_path is null
 or split_part(p_path,'/',1)<>p_user::text or p_path ~ '(^|/)[.]{1,2}(/|$)' then
 raise exception 'Invalid upload destination' using errcode='22023';end if;
 insert into material_upload_intents(user_id,subject_id,material_id,bucket,object_path,source_hash)
 values(p_user,m.subject_id,m.id,p_bucket,p_path,p_hash) on conflict(bucket,object_path) do nothing;
 select * into item from material_upload_intents where bucket=p_bucket and object_path=p_path for update;
 if item.user_id<>p_user or item.material_id is distinct from p_material or item.status<>'pending' then
 raise exception 'Upload destination changed' using errcode='40001';end if;
 return item.id;
end $$;

create or replace function register_material_upload(p_user uuid,p_material uuid,p_asset jsonb,p_metadata jsonb,p_attempts integer)
returns jsonb language plpgsql security definer set search_path=public as $$
declare m materials;j processing_tasks;intent material_upload_intents;
begin
 select * into m from materials where id=p_material and user_id=p_user for update;
 if not found then raise exception 'Material unavailable' using errcode='42501';end if;
 select * into intent from material_upload_intents where material_id=m.id and user_id=p_user
  and bucket=p_asset->>'bucket' and object_path=p_asset->>'object_path' for update;
 if not found or intent.status<>'pending' or intent.source_hash is distinct from m.source_hash then
 raise exception 'Upload intent unavailable' using errcode='40001';end if;
 if m.status<>'queued' or p_attempts is null or p_attempts not between 1 and 10
 or p_asset->>'sha256' is distinct from m.source_hash then raise exception 'Invalid upload' using errcode='22023';end if;
 insert into material_assets(user_id,subject_id,material_id,asset_type,bucket,object_path,content_type,file_size,sha256,expires_at)
 values(p_user,m.subject_id,m.id,'original',intent.bucket,intent.object_path,m.content_type,m.file_size,m.source_hash,(p_asset->>'expires_at')::timestamptz);
 insert into processing_tasks(user_id,subject_id,material_id,idempotency_key,max_attempts,metadata)
 values(p_user,m.subject_id,m.id,'material:'||m.id||':'||m.source_hash,p_attempts,coalesce(p_metadata,'{}')) returning * into j;
 update material_upload_intents set status='registered',error_code=null where id=intent.id;
 return to_jsonb(j);
end $$;

create function ready_upload_cleanup(p_limit integer default 50,p_grace integer default 3600,p_user uuid default null) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare result jsonb;
begin
 if p_limit is null or p_limit not between 1 and 100 or p_grace is null or p_grace not between 300 and 86400 then
 raise exception 'Invalid cleanup bounds' using errcode='22023';end if;
 select coalesce(jsonb_agg(to_jsonb(q)),'[]') into result from (
 select id,user_id from material_upload_intents where (p_user is null or user_id=p_user)
 and status in ('pending','cleaning') and created_at<now()-make_interval(secs=>p_grace)
 and coalesce(lease_until,'-infinity')<=now() and coalesce(retry_at,'-infinity')<=now()
 order by created_at,id limit p_limit) q;
 return result;
end $$;

create function claim_upload_cleanup(p_intent uuid,p_grace integer default 3600) returns jsonb
language plpgsql security definer set search_path=public as $$
declare item material_upload_intents;
begin
 if p_grace is null or p_grace not between 300 and 86400 then raise exception 'Invalid grace' using errcode='22023';end if;
 select * into item from material_upload_intents where id=p_intent for update skip locked;
 if not found or item.status not in ('pending','cleaning') or item.created_at>=now()-make_interval(secs=>p_grace)
 or item.lease_until>now() or item.retry_at>now() then return null;end if;
 if exists(select 1 from material_assets where bucket=item.bucket and object_path=item.object_path) then
  update material_upload_intents set status='registered',claim_token=null,lease_until=null where id=item.id;return null;
 end if;
 update material_upload_intents set status='cleaning',attempts=attempts+1,claim_token=gen_random_uuid(),lease_until=now()+interval '2 minutes'
 where id=item.id returning * into item;
 return to_jsonb(item);
end $$;

create function finish_upload_cleanup(p_intent uuid,p_token uuid,p_error text default null) returns boolean
language plpgsql security definer set search_path=public as $$
declare item material_upload_intents;
begin
 select * into item from material_upload_intents where id=p_intent and status='cleaning' and claim_token=p_token and lease_until>now() for update;
 if not found then return false;end if;
 update material_upload_intents set status=case when p_error is null then 'cleaned' else 'pending' end,
  claim_token=null,lease_until=null,error_code=left(p_error,80),
  retry_at=case when p_error is null then null else now()+make_interval(secs=>least(86400,60*power(2,least(attempts,11)))::integer) end
 where id=item.id;
 if p_error is null then
  update materials set status='failed',error_message='上传未完成，原件已清理，请重新上传'
   where id=item.material_id and user_id=item.user_id and status='queued'
    and not exists(select 1 from processing_tasks where material_id=item.material_id);
 end if;
 return true;
end $$;
revoke all on function prepare_material_upload(uuid,uuid,text,text,text),ready_upload_cleanup(integer,integer,uuid),
 claim_upload_cleanup(uuid,integer),finish_upload_cleanup(uuid,uuid,text) from public,anon,authenticated;
grant execute on function prepare_material_upload(uuid,uuid,text,text,text),ready_upload_cleanup(integer,integer,uuid),
 claim_upload_cleanup(uuid,integer),finish_upload_cleanup(uuid,uuid,text) to service_role;
notify pgrst,'reload schema';
commit;
