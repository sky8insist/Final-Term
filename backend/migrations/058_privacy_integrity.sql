begin;

-- Auth cascades execute triggers as supabase_auth_admin. Keep grants narrow:
-- only these trigger functions elevate; no application table grants to Auth.
alter function public.mark_study_plan_changed() security definer;
alter function public.invalidate_deleted_memory_snapshots() security definer;
revoke all on function public.mark_study_plan_changed(),public.invalidate_deleted_memory_snapshots()
 from public,anon,authenticated;

-- RESTRICT checks can fire before sibling cascades have deleted references
-- during auth.users deletion. NO ACTION keeps the same reference protection,
-- evaluated at commit after every cascade has completed.
alter table exams drop constraint exams_blueprint_id_fkey;
alter table exams add constraint exams_blueprint_id_fkey foreign key(blueprint_id) references exam_blueprints(id) on delete no action deferrable initially deferred;
alter table exam_questions drop constraint exam_questions_question_id_fkey;
alter table exam_questions add constraint exam_questions_question_id_fkey foreign key(question_id) references questions(id) on delete no action deferrable initially deferred;
alter table exam_responses drop constraint exam_responses_question_id_fkey;
alter table exam_responses add constraint exam_responses_question_id_fkey foreign key(question_id) references questions(id) on delete no action deferrable initially deferred;
alter table grading_results drop constraint grading_results_question_id_fkey;
alter table grading_results add constraint grading_results_question_id_fkey foreign key(question_id) references questions(id) on delete no action deferrable initially deferred;
alter table wrong_answers drop constraint wrong_answers_question_id_fkey;
alter table wrong_answers add constraint wrong_answers_question_id_fkey foreign key(question_id) references questions(id) on delete no action deferrable initially deferred;

-- A single SQL statement snapshot, without PostgREST's per-table row cap.
-- Include all public owner tables (including legacy text user_id), plus children
-- without user_id reached exclusively through owned parents. Never auth secrets.
create or replace function public.export_privacy_bundle(p_user uuid) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare tab text; rows jsonb; data jsonb:='{}';
begin
 if not exists(select 1 from auth.users where id=p_user) then
  raise exception 'Account unavailable' using errcode='42501';end if;
 for tab in select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
  join pg_attribute a on a.attrelid=c.oid and a.attname='user_id' and not a.attisdropped
  where n.nspname='public' and c.relkind in ('r','p') and not c.relispartition order by c.relname loop
  execute format('select coalesce(jsonb_agg(to_jsonb(t)),''[]''::jsonb) from public.%I t where t.user_id::text=$1',tab)
   into rows using p_user::text;
  data:=data||jsonb_build_object(tab,rows);
 end loop;
 data:=data||jsonb_build_object(
  'profiles',(select coalesce(jsonb_agg(to_jsonb(p)),'[]') from profiles p where id=p_user),
  'exam_sections',(select coalesce(jsonb_agg(to_jsonb(s)),'[]') from exam_sections s join exams e on e.id=s.exam_id where e.user_id=p_user),
  'exam_questions',(select coalesce(jsonb_agg(to_jsonb(q)),'[]') from exam_questions q join exams e on e.id=q.exam_id where e.user_id=p_user),
  'question_versions',(select coalesce(jsonb_agg(to_jsonb(v)),'[]') from question_versions v join questions q on q.id=v.question_id where q.user_id=p_user));
 return jsonb_build_object('exportedAt',statement_timestamp(),'userId',p_user,'data',data);
end $$;

-- External storage/index cleanup must finish before invoking this transaction.
-- Failure of any SQL step rolls back ALL relational deletes and revocation.
create or replace function public.delete_privacy_learning_data(p_user uuid) returns void
language plpgsql security definer set search_path=public as $$
declare tab text;
begin
 perform 1 from auth.users where id=p_user for update;
 if not found then raise exception 'Account unavailable' using errcode='42501';end if;
 perform set_config('app.plan_generation','on',true);
 delete from wrong_answers where user_id=p_user;
 delete from grading_results where user_id=p_user;
 delete from exam_responses where user_id=p_user;
 delete from exam_attempts where user_id=p_user;
 delete from exam_questions where exam_id in(select id from exams where user_id=p_user);
 delete from exams where user_id=p_user;
 delete from questions where user_id=p_user;
 delete from exam_blueprints where user_id=p_user;
 delete from subjects where user_id=p_user;
 -- Clear global/null-subject rows, audit logs and legacy Dayend records too.
 for tab in select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
  join pg_attribute a on a.attrelid=c.oid and a.attname='user_id' and not a.attisdropped
  where n.nspname='public' and c.relkind in ('r','p') and not c.relispartition order by c.relname loop
  execute format('delete from public.%I where user_id::text=$1',tab) using p_user::text;
 end loop;
 perform revoke_workspace_snapshots(p_user);
end $$;
revoke all on function public.export_privacy_bundle(uuid),public.delete_privacy_learning_data(uuid) from public,anon,authenticated;
grant execute on function public.export_privacy_bundle(uuid),public.delete_privacy_learning_data(uuid) to service_role;
notify pgrst,'reload schema';
commit;
