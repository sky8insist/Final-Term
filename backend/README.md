# Exam AI Assistant Backend

FastAPI backend skeleton for a short-term exam review assistant.

## Run

```bash
uvicorn app.main:app --reload
```

## Layers

- `api/`: HTTP endpoints
- `services/`: file parsing, chunking, embeddings, RAG, LLM, memory, evaluation
- `agents/`: router, planner, retriever, generator, evaluator
- `db/`: Supabase and vector storage adapters
- `models/`: shared domain schemas

## Acceptance

End-to-end MVP acceptance tooling lives in `scripts/`.

```bash
python scripts/e2e_acceptance.py --generate-only
python scripts/e2e_acceptance.py
```

See `scripts/README.md` for required local services and environment variables.

## MinerU document parsing

`POST /api/v1/materials/uploads` keeps the existing private Storage and Celery
pipeline, but routes PDF, Word, PowerPoint, Excel, and image parsing through the
MinerU v4 precise API. Set `MINERU_API_TOKEN` in the root `.env` (the previous
experiment-only `MINERU_AB_TOKEN` is accepted as a compatibility alias).

Documents explicitly submit with OCR disabled. Direct image uploads enable
image recognition. Native parsing/OCR is fallback-only and is annotated in
content block metadata with `fallbackParser` and `fallbackReason`.
