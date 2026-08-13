# Baseline acceptance

Run from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

Run from `frontend/`:

```powershell
npm run build
```

Baseline guarantees:

- Legacy business routes remain mounted at their original paths.
- The same business routes are available under `/api/v1`.
- API errors have a stable `success/error/code/message/requestId` shape.
- Every HTTP response exposes `X-Request-ID`.
- Source files and prompts use UTF-8.
- Implemented major features are enabled by default; external web knowledge remains explicit opt-in.

## Latest verification (2026-07-26)

- Backend: `88 passed` (`pytest -q -p no:cacheprovider`).
- Quality schemas/intent set: passed (`scripts/run_quality_eval.py`).
- Frontend: TypeScript and Vite production build passed (113 modules).
- Frontend dependency audit: 0 known vulnerabilities.
- Docker worker Compose configuration: valid without requiring a local `.env` file.
- Static phase matrix: all steps 00–15 passed (`scripts/verify_plan_coverage.py`).
- Database migrations 001–020: applied successfully twice to an isolated Supabase Postgres database.
- Database invariants: Chinese structured retrieval, traceable chunks, audio segment isolation, session search and cross-user RLS passed in a rollback transaction.
- Acceptance fixtures: TXT, PDF and DOCX generated successfully.

Full service acceptance remains environment-dependent. It requires configured Supabase keys,
database URL and cloud model credentials, then running migrations 001–020, Redis/Celery, and
`scripts/e2e_acceptance.py --full`. Full audio acceptance also requires `ACCEPTANCE_AUDIO_FILE`.
Never use the placeholder production secrets from example files.
