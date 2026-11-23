begin;
alter table public.exam_responses add column learner_confidence double precision
    check (learner_confidence between 0 and 1);
alter table public.grading_results add column learner_confidence double precision
    check (learner_confidence between 0 and 1),
    add column confidence_mismatch double precision check (confidence_mismatch between 0 and 1);
commit;
