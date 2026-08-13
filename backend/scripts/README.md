# Acceptance Scripts

This folder contains operational checks for the MVP end-to-end chain. They are not unit tests: they call the running backend, Supabase Auth, Postgres, embedding service, LightRAG, and LLM.

## Standard Dataset

Generate the fixture files only:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_acceptance.py --generate-only
```

The files are written to `backend/data/acceptance/`:

- `linear_algebra_core.txt`
- `linear_algebra_cases.pdf`
- `linear_algebra_mistakes.docx`
- `database_core.txt`

The TXT and DOCX fixtures contain the Chinese source text from the acceptance plan. The PDF fixture uses dependency-free ASCII text with the same `LA-P1` / `LA-P2` / `LA-P3` markers so the current `pypdf` parser can extract it without adding a PDF generation package or CJK font dependency.

## Run Acceptance

Start local Supabase and the backend first, then run:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_acceptance.py
```

If the local database has not applied all migrations, run:

```powershell
.\.venv\Scripts\python.exe scripts\e2e_acceptance.py --apply-migrations
```

Required configuration is read from the project-root `.env` unless supplied explicitly:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `DATABASE_URL`
- `ACCEPTANCE_API_BASE_URL` optional, defaults to `http://localhost:8000`

The script creates or logs in:

- `student_a@example.com / Test123456!`
- `student_b@example.com / Test123456!`

It then verifies schema, auth, subject isolation, material upload, retrieval citations, chat answers, insufficient-context behavior, chat history, review progress, and cross-subject isolation.
