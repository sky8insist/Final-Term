begin;
-- Completion receipts and task-result metadata are trusted server evidence.
-- All writes continue through scoped APIs using service_role, never browser SQL.
do $$ declare tab text; pol record; begin
    foreach tab in array array['processing_tasks','learning_events'] loop
        for pol in select policyname from pg_policies where schemaname='public' and tablename=tab loop
            execute format('drop policy %I on public.%I',pol.policyname,tab);
        end loop;
        execute format('create policy "Owners read progress %s" on public.%I for select to authenticated using(user_id=auth.uid())',tab,tab);
    end loop;
end $$;
-- Interactions can contain hidden evaluation answers and remain backend-only.
revoke all on table public.learning_interactions from authenticated;
commit;
