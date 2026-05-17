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
