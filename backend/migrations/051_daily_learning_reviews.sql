begin;
create table public.daily_learning_reviews (
 id uuid primary key default gen_random_uuid(),user_id uuid not null,subject_id uuid not null,
 request_id uuid not null,day date not null,source jsonb not null,report jsonb not null,
 status text not null default 'pending' check(status in ('pending','applied','rejected')),
 version integer not null default 1,created_at timestamptz not null default now(),
 unique(user_id,request_id),foreign key(subject_id,user_id) references subjects(id,user_id) on delete cascade
);
alter table public.daily_learning_reviews enable row level security;
create policy "Read own daily reviews" on public.daily_learning_reviews for select to authenticated using(user_id=auth.uid());
revoke all on public.daily_learning_reviews from public,anon,authenticated;
grant select on public.daily_learning_reviews to authenticated;
grant all on public.daily_learning_reviews to service_role;
create index mastery_daily_key_idx on public.mastery_history(user_id,subject_id,knowledge_key,created_at desc,id);

create function public.daily_learning_source(p_user uuid,p_subject uuid,p_day date) returns jsonb
language plpgsql stable security definer set search_path=public as $$
declare start_at timestamptz; end_at timestamptz; topics jsonb; done jsonb; tomorrow jsonb; candidates jsonb;
begin
 if not exists(select 1 from subjects where id=p_subject and user_id=p_user) then raise exception 'Subject unavailable' using errcode='42501'; end if;
 if p_day is distinct from (now() at time zone 'Asia/Shanghai')::date then raise exception 'Current Shanghai day required' using errcode='22023'; end if;
 start_at:=p_day::timestamp at time zone 'Asia/Shanghai';end_at:=(p_day+1)::timestamp at time zone 'Asia/Shanghai';
 select coalesce(jsonb_agg(jsonb_build_object('id',t.id,'title',t.title,'mastery',to_jsonb(m),'covered',cv.knowledge_point_id is not null,
   'before',b.mastery,'after',a.mastery,'lastEvidenceId',a.id) order by t.id),'[]') into topics
 from knowledge_points t
 left join knowledge_mastery m on m.user_id=p_user and m.subject_id=p_subject and m.knowledge_key=t.knowledge_key
 left join topic_coverage cv on cv.user_id=p_user and cv.subject_id=p_subject and cv.knowledge_point_id=t.id
 left join lateral(select h.mastery from mastery_history h where h.user_id=p_user and h.subject_id=p_subject and h.knowledge_key=t.knowledge_key
   and h.created_at<start_at order by h.created_at desc,h.id desc limit 1)b on true
 left join lateral(select h.id,h.mastery from mastery_history h where h.user_id=p_user and h.subject_id=p_subject and h.knowledge_key=t.knowledge_key
   and h.created_at>=start_at and h.created_at<end_at order by h.created_at desc,h.id desc limit 1)a on true
 where t.user_id=p_user and t.subject_id=p_subject and not t.archived;
 select coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'minutes',estimated_minutes,'completedAt',completed_at) order by id),'[]') into done
 from review_tasks where user_id=p_user and subject_id=p_subject and status='completed' and completed_at>=start_at and completed_at<end_at;
 select coalesce(jsonb_agg(jsonb_build_object('id',t.id,'title',t.title,'minutes',t.estimated_minutes,'topicId',t.knowledge_point_id,
   'status',t.status,'locked',t.locked) order by t.priority desc,t.id),'[]') into tomorrow
 from review_tasks t join study_plans p on p.id=t.plan_id and p.user_id=p_user and p.status='active'
 where t.user_id=p_user and t.subject_id=p_subject and t.scheduled_date=p_day+1 and t.status<>'skipped';
 select coalesce(jsonb_agg(jsonb_build_object('id',t.id,'planId',p.id,'planVersion',p.version,'title',t.title,
   'topicId',t.knowledge_point_id,'minutes',t.estimated_minutes,'from',t.scheduled_date,
   'slotKey',jsonb_build_array(t.plan_id,t.knowledge_key,t.task_type)::text) order by t.priority desc,t.id),'[]') into candidates
 from review_tasks t join study_plans p on p.id=t.plan_id and p.user_id=p_user and p.status='active'
 join knowledge_points k on k.id=t.knowledge_point_id and k.user_id=p_user and k.subject_id=p_subject and not k.archived
 where t.user_id=p_user and t.subject_id=p_subject and t.source='system' and not t.locked and t.status in ('pending','overdue')
 and t.scheduled_date<=p_day and p.exam_date>=p_day+1
 and not exists(select 1 from review_tasks x where x.plan_id=t.plan_id and x.user_id=p_user and x.knowledge_key=t.knowledge_key and x.task_type=t.task_type and x.scheduled_date=p_day+1);
 return jsonb_build_object('day',p_day,'timezone','Asia/Shanghai','topics',topics,'completedTasks',done,'tomorrowTasks',tomorrow,'candidates',candidates,
   'submittedTodayGradedAttempts',(select count(*) from exam_attempts where user_id=p_user and subject_id=p_subject and status='graded' and submitted_at>=start_at and submitted_at<end_at),
   'learningEvents',(select coalesce(jsonb_object_agg(event_type,n),'{}') from (select event_type,count(*) n from learning_events where user_id=p_user and subject_id=p_subject and created_at>=start_at and created_at<end_at group by event_type)e),
   'exams',(select coalesce(jsonb_agg(jsonb_build_object('id',id,'title',title,'date',exam_date) order by id),'[]') from exam_events where user_id=p_user and subject_id=p_subject and status='active' and exam_date=p_day+1),
   'capacity',(select minutes from calendar_availability where user_id=p_user and day=p_day+1),
   'usedMinutes',(select coalesce(sum(t.estimated_minutes),0) from review_tasks t join study_plans p on p.id=t.plan_id and p.user_id=p_user and p.status='active' where t.user_id=p_user and t.scheduled_date=p_day+1 and t.status<>'skipped'));
end $$;

create function public.save_daily_learning_review(p_user uuid,p_subject uuid,p_day date,p_request uuid,p_source jsonb,p_report jsonb) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved daily_learning_reviews;
begin
 perform pg_advisory_xact_lock(hashtextextended('daily-review:'||p_user::text||p_request::text,0));
 select * into saved from daily_learning_reviews where user_id=p_user and request_id=p_request;
 if found then
   if saved.subject_id<>p_subject or saved.day<>p_day then raise exception 'Request conflict' using errcode='40001'; end if;
   return to_jsonb(saved)-'source'-'user_id';
 end if;
 if p_source is distinct from daily_learning_source(p_user,p_subject,p_day) then raise exception 'Learning state changed' using errcode='40001'; end if;
 insert into daily_learning_reviews(user_id,subject_id,request_id,day,source,report) values(p_user,p_subject,p_request,p_day,p_source,p_report) returning * into saved;
 return to_jsonb(saved)-'source'-'user_id';
end $$;

create function public.decide_daily_learning_review(p_user uuid,p_review uuid,p_version integer,p_approve boolean) returns jsonb
language plpgsql security definer set search_path=public as $$
declare saved daily_learning_reviews; item jsonb; plan_version integer;
begin
 perform pg_advisory_xact_lock(hashtextextended('calendar:'||p_user::text,0));
 select * into saved from daily_learning_reviews where id=p_review and user_id=p_user for update;
 if not found then raise exception 'Review unavailable' using errcode='42501'; end if;
 if saved.status<>'pending' then
   if (saved.status='applied') is distinct from p_approve then raise exception 'Decision conflict' using errcode='40001'; end if;
   return to_jsonb(saved)-'source'-'user_id';
 end if;
 if saved.version<>p_version then raise exception 'Review changed' using errcode='40001'; end if;
 if p_approve then
   if saved.source is distinct from daily_learning_source(p_user,saved.subject_id,saved.day) then raise exception 'Learning state changed' using errcode='40001'; end if;
   for item in select * from jsonb_array_elements(saved.report->'proposedMoves') loop
     if not exists(select 1 from jsonb_array_elements(saved.source->'candidates') c where c->>'id'=item->>'taskId' and c->>'planId'=item->>'planId'
       and c->>'minutes'=item->>'minutes' and c->>'topicId'=item->>'topicId') then raise exception 'Unsupported task proposal' using errcode='22023'; end if;
     select version into plan_version from study_plans where id=(item->>'planId')::uuid and user_id=p_user and subject_id=saved.subject_id for update;
     if not found then raise exception 'Plan unavailable' using errcode='40001'; end if;
     perform move_calendar_task(p_user,(item->>'taskId')::uuid,saved.day+1,plan_version);
   end loop;
   insert into study_plan_events(user_id,subject_id,plan_id,event_type,reason,details)
   select distinct p_user,saved.subject_id,(m->>'planId')::uuid,'daily_review_applied','用户确认学习复盘改期建议',jsonb_build_object('reviewId',saved.id)
   from jsonb_array_elements(saved.report->'proposedMoves') m;
 end if;
 update daily_learning_reviews set status=case when p_approve then 'applied' else 'rejected' end,version=version+1 where id=p_review returning * into saved;
 return to_jsonb(saved)-'source'-'user_id';
end $$;
revoke all on function public.daily_learning_source(uuid,uuid,date),public.save_daily_learning_review(uuid,uuid,date,uuid,jsonb,jsonb),public.decide_daily_learning_review(uuid,uuid,integer,boolean) from public,anon,authenticated;
grant execute on function public.daily_learning_source(uuid,uuid,date),public.save_daily_learning_review(uuid,uuid,date,uuid,jsonb,jsonb),public.decide_daily_learning_review(uuid,uuid,integer,boolean) to service_role;
notify pgrst,'reload schema';
commit;
