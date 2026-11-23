begin;
-- artifacts_scope_unique is already installed by 029_course_structure.sql.
create table public.flashcards (
    artifact_id uuid not null,card_id text not null,user_id uuid not null,subject_id uuid not null,
    knowledge_point_id uuid,knowledge_key text,front text not null,back text not null,
    content_version integer not null default 1,archived boolean not null default false,
    primary key(artifact_id,card_id),unique(artifact_id,card_id,user_id,subject_id),
    foreign key(artifact_id,user_id,subject_id) references public.artifacts(id,user_id,subject_id) on delete cascade,
    foreign key(knowledge_point_id,user_id,subject_id) references public.knowledge_points(id,user_id,subject_id) on delete cascade
);
create table public.flashcard_review_state (
    artifact_id uuid not null,card_id text not null,user_id uuid not null,subject_id uuid not null,
    difficulty double precision not null default 5 check(difficulty between 1 and 10),
    stability double precision not null default 0.25 check(stability between 0.25 and 365),
    last_review timestamptz,next_review timestamptz not null default now(),
    review_count integer not null default 0,lapse_count integer not null default 0,
    version integer not null default 0,content_version integer not null default 1,
    primary key(artifact_id,card_id),
    foreign key(artifact_id,card_id,user_id,subject_id) references public.flashcards(artifact_id,card_id,user_id,subject_id) on delete cascade
);
create index flashcard_due_idx on public.flashcard_review_state(user_id,subject_id,next_review,artifact_id,card_id);
create table public.flashcard_review_logs (
    id uuid primary key,user_id uuid not null,subject_id uuid not null,artifact_id uuid not null,card_id text not null,
    rating text not null check(rating in ('again','hard','good','easy')),expected_version integer not null,
    content_version integer not null,reviewed_at timestamptz not null default now(),
    state_before jsonb not null,state_after jsonb not null,result jsonb not null,response_seconds double precision,
    foreign key(artifact_id,card_id,user_id,subject_id) references public.flashcards(artifact_id,card_id,user_id,subject_id) on delete cascade
);
create index flashcard_log_owner_idx on public.flashcard_review_logs(user_id,artifact_id,card_id,reviewed_at desc);
do $$ declare tab text; begin
    foreach tab in array array['flashcards','flashcard_review_state','flashcard_review_logs'] loop
        execute format('alter table public.%I enable row level security',tab);
        execute format('create policy "Owners read %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
    end loop;
end $$;

create function public.sync_flashcards_row(new public.artifacts) returns void language plpgsql set search_path=public as $$
declare card jsonb; ordinal bigint; card_key text; topic uuid; keys text[]:=array[]::text[];
begin
    if new.artifact_type<>'flashcards' then
        update flashcards set archived=true where artifact_id=new.id;
        return;
    end if;
    for card,ordinal in select value, ordinality from jsonb_array_elements(coalesce(new.content->'cards','[]'::jsonb)) with ordinality loop
        card_key:=coalesce(nullif(card->>'id',''),'legacy-'||ordinal);
        if card_key=any(keys) then raise exception 'Duplicate card ID' using errcode='23514'; end if;
        keys:=array_append(keys,card_key);
        select id into topic from knowledge_points where user_id=new.user_id and subject_id=new.subject_id
            and (id::text=card->>'knowledgePointId' or knowledge_key=card->>'knowledgeKey') order by (id::text=card->>'knowledgePointId') desc nulls last limit 1;
        if topic is null and card->>'knowledgePointId' is null and card->>'knowledgeKey' is null then
            select knowledge_point_id into topic from flashcards where artifact_id=new.id and card_id=card_key and front=coalesce(card->>'front','');
        end if;
        insert into flashcards(artifact_id,card_id,user_id,subject_id,knowledge_point_id,knowledge_key,front,back)
        values(new.id,card_key,new.user_id,new.subject_id,topic,coalesce((select knowledge_key from knowledge_points where id=topic),card->>'knowledgeKey'),coalesce(card->>'front',''),coalesce(card->>'back',''))
        on conflict(artifact_id,card_id) do update set front=excluded.front,back=excluded.back,knowledge_point_id=excluded.knowledge_point_id,
            knowledge_key=excluded.knowledge_key,archived=false,content_version=flashcards.content_version+
                case when flashcards.front is distinct from excluded.front or flashcards.back is distinct from excluded.back or
                    flashcards.knowledge_point_id is distinct from excluded.knowledge_point_id or
                    flashcards.knowledge_key is distinct from excluded.knowledge_key or flashcards.archived then 1 else 0 end;
        insert into flashcard_review_state(artifact_id,card_id,user_id,subject_id) values(new.id,card_key,new.user_id,new.subject_id) on conflict do nothing;
    end loop;
    update flashcards set archived=true where artifact_id=new.id and not(card_id=any(keys));
    update flashcard_review_state s set difficulty=5,stability=0.25,last_review=null,next_review=now(),review_count=0,lapse_count=0,
        version=s.version+1,content_version=c.content_version from flashcards c
        where s.artifact_id=new.id and c.artifact_id=s.artifact_id and c.card_id=s.card_id and s.content_version<>c.content_version;
    return;
end; $$;
revoke all on function public.sync_flashcards_row(public.artifacts) from public,anon,authenticated;
grant execute on function public.sync_flashcards_row(public.artifacts) to service_role;
create function public.sync_flashcards() returns trigger language plpgsql set search_path=public as $$
begin perform public.sync_flashcards_row(new); return null; end; $$;
create trigger artifact_flashcards_sync after insert or update of content,artifact_type on public.artifacts
    for each row execute function public.sync_flashcards();
-- Stable synthetic IDs support legacy decks without changing their original JSON.
do $$ declare item public.artifacts; begin
    for item in select * from public.artifacts where artifact_type='flashcards' loop
        perform public.sync_flashcards_row(item);
    end loop;
end $$;

create function public.commit_flashcard_review(p_user_id uuid,p_artifact_id uuid,p_card_id text,p_request_id uuid,
    p_expected_version integer,p_rating text,p_values jsonb) returns jsonb language plpgsql set search_path=public as $$
declare card public.flashcards; state public.flashcard_review_state; old public.flashcard_review_logs;
    saved public.flashcard_review_state; mastery public.knowledge_mastery; result jsonb; m jsonb; evidence jsonb;
    topic public.knowledge_points; inserted boolean;
begin
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text||':'||p_request_id::text,0));
    select * into old from flashcard_review_logs where id=p_request_id;
    if found then
        if old.user_id<>p_user_id or old.artifact_id<>p_artifact_id or old.card_id<>p_card_id or old.rating<>p_rating or old.expected_version<>p_expected_version
            then raise exception 'Review request already used' using errcode='40001'; end if;
        return old.result;
    end if;
    select * into card from flashcards where artifact_id=p_artifact_id and card_id=p_card_id and user_id=p_user_id for update;
    if not found or card.archived then raise exception 'Card not found' using errcode='42501'; end if;
    if exists(select 1 from knowledge_points where id=card.knowledge_point_id and archived) then raise exception 'Topic archived' using errcode='40001'; end if;
    select * into state from flashcard_review_state where artifact_id=p_artifact_id and card_id=p_card_id for update;
    if state.version<>p_expected_version then raise exception 'Card changed' using errcode='40001'; end if;
    m:=p_values->'mastery'; evidence:=p_values->'evidence';
    select * into topic from knowledge_points where id=(p_values->>'topicId')::uuid and user_id=p_user_id
        and subject_id=card.subject_id and knowledge_key=m->>'knowledge_key' for share;
    if not found or topic.archived or (card.knowledge_point_id is not null and card.knowledge_point_id<>topic.id) then
        raise exception 'Topic changed' using errcode='40001'; end if;
    update flashcards set knowledge_point_id=topic.id,knowledge_key=topic.knowledge_key where artifact_id=p_artifact_id and card_id=p_card_id;
    insert into knowledge_mastery(user_id,subject_id,knowledge_key) values(p_user_id,card.subject_id,m->>'knowledge_key') on conflict do nothing;
    inserted:=found;
    select * into mastery from knowledge_mastery where user_id=p_user_id and subject_id=card.subject_id and knowledge_key=m->>'knowledge_key' for update;
    if p_values->>'masteryUpdatedAt' is null then
        if not inserted then raise exception 'Mastery changed' using errcode='40001'; end if;
    elsif mastery.updated_at is distinct from (p_values->>'masteryUpdatedAt')::timestamptz then
        raise exception 'Mastery changed' using errcode='40001';
    end if;
    update flashcard_review_state set difficulty=(p_values->>'difficulty')::double precision,
        stability=(p_values->>'stability')::double precision,next_review=(p_values->>'nextReview')::timestamptz,
        last_review=(p_values->>'reviewedAt')::timestamptz,review_count=review_count+1,
        lapse_count=lapse_count+case when p_rating='again' then 1 else 0 end,version=version+1
        where artifact_id=p_artifact_id and card_id=p_card_id returning * into saved;
    update knowledge_mastery set mastery=(m->>'mastery')::double precision,confidence=(m->>'confidence')::double precision,
        attempts=(m->>'attempts')::integer,correct_attempts=(m->>'correct_attempts')::integer,
        last_reviewed_at=(m->>'last_reviewed_at')::timestamptz,next_review_at=(m->>'next_review_at')::timestamptz,
        metadata=m->'metadata',updated_at=now() where id=mastery.id returning * into mastery;
    insert into mastery_history(user_id,subject_id,knowledge_key,mastery,confidence,correct,difficulty,evidence)
        values(p_user_id,card.subject_id,mastery.knowledge_key,mastery.mastery,mastery.confidence,p_rating in ('good','easy'),'medium',evidence);
    insert into learning_events(user_id,subject_id,event_type,payload) values(p_user_id,card.subject_id,'flashcard_review',
        jsonb_build_object('artifactId',p_artifact_id,'cardId',p_card_id,'rating',p_rating,'knowledgeKey',mastery.knowledge_key,'reviewId',p_request_id));
    result:=jsonb_build_object('rating',p_rating,'reviewId',p_request_id,'state',to_jsonb(saved),'mastery',to_jsonb(mastery));
    insert into flashcard_review_logs(id,user_id,subject_id,artifact_id,card_id,rating,expected_version,content_version,state_before,state_after,result,response_seconds)
        values(p_request_id,p_user_id,card.subject_id,p_artifact_id,p_card_id,p_rating,p_expected_version,card.content_version,
            to_jsonb(state),to_jsonb(saved),result,(p_values->>'responseSeconds')::double precision);
    return result;
end; $$;
revoke all on function public.commit_flashcard_review(uuid,uuid,text,uuid,integer,text,jsonb) from public,anon,authenticated;
grant execute on function public.commit_flashcard_review(uuid,uuid,text,uuid,integer,text,jsonb) to service_role;

-- One statement keeps queue counts and the returned cards at the same snapshot.
create function public.flashcard_queue(p_user_id uuid,p_subject_id uuid default null,p_artifact_id uuid default null,
    p_include_future boolean default false,p_limit integer default 50) returns jsonb language sql stable set search_path=public as $$
    with eligible as (
        select c.*,to_jsonb(s) as state,s.next_review,s.last_review,sub.name as subject_name
        from flashcards c join flashcard_review_state s using(artifact_id,card_id,user_id,subject_id)
        join subjects sub on sub.id=c.subject_id and sub.user_id=p_user_id
        left join knowledge_points t on t.id=c.knowledge_point_id
        where c.user_id=p_user_id and not c.archived and (t.id is null or not t.archived)
            and (p_subject_id is null or c.subject_id=p_subject_id) and (p_artifact_id is null or c.artifact_id=p_artifact_id)
    ), page as (
        select * from eligible where p_include_future or next_review<=now()
        order by next_review,artifact_id,card_id limit least(greatest(p_limit,1),200)+1
    ), stats as (
        select subject_id,subject_name,count(*) as total,
            count(*) filter(where next_review<=now()) as due,
            count(*) filter(where last_review is not null and next_review<date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai') as overdue,
            min(next_review) as next_review from eligible group by subject_id,subject_name
    ) select jsonb_build_object('cards',coalesce((select jsonb_agg(to_jsonb(p)-'last_review'-'next_review'||jsonb_build_object('overdue',p.last_review is not null and p.next_review<date_trunc('day',now() at time zone 'Asia/Shanghai') at time zone 'Asia/Shanghai')) from (select * from page limit least(greatest(p_limit,1),200)) p),'[]'::jsonb),
        'hasMore',(select count(*)>least(greatest(p_limit,1),200) from page),'asOf',now(),
        'subjects',coalesce((select jsonb_agg(to_jsonb(stats) order by subject_name,subject_id) from stats),'[]'::jsonb),
        'dueCount',(select count(*) from eligible where next_review<=now()),'totalCount',(select count(*) from eligible));
$$;
revoke all on function public.flashcard_queue(uuid,uuid,uuid,boolean,integer) from public,anon,authenticated;
grant execute on function public.flashcard_queue(uuid,uuid,uuid,boolean,integer) to service_role;
commit;
