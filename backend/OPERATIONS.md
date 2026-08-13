# Operations and recovery

## Quality gates

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests
.\.venv\Scripts\python.exe scripts\run_quality_eval.py
.\.venv\Scripts\python.exe scripts\verify_plan_coverage.py
```

Run `scripts/e2e_acceptance.py --full` with Supabase, Redis, the worker, configured model APIs,
and `ACCEPTANCE_AUDIO_FILE` pointing to a clear MP3/WAV/M4A lecture recording. Full mode covers
async ingestion, timestamped audio, role switching, frozen memory, artifacts, exams, grading,
wrong-answer/mastery updates, and spaced study plans.

Database-only acceptance can be repeated against an isolated Supabase Postgres container with
`scripts/sql/acceptance_invariants.sql`; it runs in a transaction and rolls back its fixture rows.

## Services

- API: `uvicorn app.main:app`
- Worker: `celery -A app.worker.celery_app:celery_app worker --loglevel=info`
- Scheduler: `celery -A app.worker.celery_app:celery_app beat --loglevel=info`
- Redis: use `docker-compose.worker.yml`

## MinerU operations

- Required for the primary document path: `ENABLE_MINERU=true` and a valid
  `MINERU_API_TOKEN` in the root `.env`. Restart both API and Celery workers
  after changing parser configuration.
- MinerU batch identifiers and remote states are persisted in
  `processing_tasks.metadata.mineru`. A Celery retry resumes the same uploaded
  batch instead of submitting it again.
- Polling is bounded by `MINERU_TIMEOUT_SECONDS`; API calls, signed upload, and
  result download retry transient network/429/5xx failures. Result Zip size and
  expanded size are independently capped, and archive paths are validated.
- `material_assets` stores `mineru_result` and `mineru_markdown` in the same
  private bucket and retention policy as originals. Never log signed URLs or
  the MinerU token.
- Uploaded documents leave the deployment and are processed by MinerU. This
  third-party processing must be reflected in the production privacy notice
  and data-processing policy.

After configuring the token, a non-sensitive live format check is available:

```powershell
.\.venv\Scripts\python.exe scripts\mineru_smoke_test.py
```

Emergency rollback: set `ENABLE_MINERU=false` and restart workers. Supported
native formats will use the local fallback; legacy `.doc`, `.ppt`, and `.xls`
will fail explicitly until MinerU is restored. To disable fallback instead,
set `MINERU_ENABLE_LOCAL_FALLBACK=false`.

## Backup and restore

Back up Postgres with `pg_dump --format=custom` and the private `study-materials` bucket on the same schedule. Restore into an isolated database first, apply pending migrations, then run the complete acceptance suite before switching traffic. Never log database URLs or storage credentials.

## Data lifecycle

Original material assets expire after `ORIGINAL_FILE_RETENTION_DAYS`; Celery Beat removes expired objects daily. Derived blocks remain until the user deletes the subject or account. Privacy export and deletion are available under `/api/v1/privacy`.
