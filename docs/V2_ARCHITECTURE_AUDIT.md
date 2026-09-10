# V2 Architecture Audit

Status: completed before V3 implementation. This audit records the current Exam AI
Assistant codebase; the V3 Dayend workflow is additive and does not replace its
exam-review endpoints.

## Classification legend

`KEEP` = deterministic infrastructure or unrelated existing product capability.
`MIGRATE_TO_AGENT` = semantic decision-making which must be isolated from the
V3 multi-agent execution path. `CONVERT_TO_TOOL` = read-only capability suitable
for an agent tool. `KEEP_AS_DEMO_ONLY` = mock implementation, never a fallback in
`DAYEND_MODE=multi_agent`. `REMOVE` = obsolete only after callers are migrated.

| File / group | Current responsibility | LLM | Rule | Mock | V3 action |
|---|---|---:|---:|---:|---|
| `app/main.py`, `api/router.py`, `api/deps.py`, `utils/*` | FastAPI mounting, error handling, auth dependency, response utilities | No | Yes | No | KEEP |
| `config/settings.py` | Environment configuration and feature flags | No | Yes | No | KEEP; add isolated Dayend settings |
| `providers/openai_compatible.py`, `services/llm_service.py` | Provider transport and existing JSON/text generation | Yes | No | Yes | KEEP; do not use its JSON-repair path for V3 structured contracts |
| `agents/router_agent.py` | Existing study-assistant intent routing; includes LLM failure rule fallback | Yes | Yes | No | KEEP for V2 only; do not reuse in multi-agent mode |
| `services/assistant_service.py`, `api/assistant.py`, `models/assistant.py` | Existing study chat orchestration and DTOs | Yes | Yes | No | KEEP; V3 receives a separate `/api/v3` adapter |
| `services/dialogue_act_service.py`, `services/conversation_context_service.py` | Dialogue interpretation and chat context | Yes | Yes | No | KEEP; CONVERT_TO_TOOL only if V3 later needs read-only session context |
| `services/study_plan_service.py`, `services/study_plan_generation_service.py`, `api/study_plans.py`, `models/study_plan.py` | Course study-plan persistence/generation | Yes | Yes | No | KEEP; V3 planning uses separate tomorrow-plan records |
| `services/memory_service.py`, `services/hermes_memory_service.py`, `api/memory.py`, `models/memory.py` | Chat/history/profile persistence | Yes | Yes | No | CONVERT_TO_TOOL for V3 read-only session/history access |
| `db/supabase_client.py`, `db/vector_store.py`, `migrations/*` | Database and vector-store adapters | No | Yes | No | KEEP; add V3 migration without coupling it to checkpoints |
| `services/task_service.py`, `services/generation_task_service.py`, `worker/*`, `api/tasks.py`, `models/task.py` | Background task infrastructure | No | Yes | No | KEEP |
| `services/observability_service.py`, `api/operations.py` | Existing request/model metrics | No | Yes | No | KEEP; extend with V3 trace metrics |
| `services/security_service.py`, `services/privacy_service.py`, `api/privacy.py` | Access control/privacy deletion | No | Yes | No | KEEP |
| `services/retrieval_service.py`, `services/rag_service.py`, `services/lightrag_service.py`, `services/embedding_service.py`, `services/external_search_service.py`, `api/retrieval.py` | Retrieval and grounded study answers | Yes | Yes | Yes | KEEP; no default V3 agent context injection |
| `services/material_service.py`, `services/ingestion_service.py`, `services/parse_service.py`, `services/mineru_*`, `services/file_service.py`, `api/materials.py`, `models/material.py`, `models/content.py`, `models/chunk.py` | Material ingestion/parsing | Yes | Yes | Yes | KEEP |
| `services/exam_*`, `api/exams.py`, `api/exam_attempts.py`, `models/exam.py` | Exam generation, retrieval and attempts | Yes | Yes | Yes | KEEP |
| `services/answer_evaluation_service.py`, `services/evidence_assessment_service.py`, `services/mastery_service.py`, `services/quality_eval_service.py` | Learning/evidence evaluation | Yes | Yes | No | KEEP |
| `services/audio_service.py`, `services/multimodal_service.py` | Audio/image model capabilities | Yes | Yes | Yes | KEEP |
| `services/role_service.py`, `services/study_signal_service.py`, `services/learning_interaction_service.py`, `services/question_context_service.py` | Study UX orchestration | Yes | Yes | No | KEEP |
| `services/artifact_service.py`, `api/artifacts.py`, `models/artifact.py` | Learning artifacts | Yes | Yes | No | KEEP |
| `mindmap/*`, `api/review.py`, `api/workspace.py`, `api/subjects.py`, `models/subject.py`, `models/review.py` | Existing product features | Yes | Yes | No | KEEP |
| `services/mock_external_service.py`, mock branches in existing services | Offline V2 test support | No | Yes | Yes | KEEP_AS_DEMO_ONLY; V3 traces must label simulation |
| `tests/*`, `scripts/*`, `evals/*` | Existing product verification/evaluation | Mixed | Mixed | Mixed | KEEP; add isolated `tests/agents`, `tests/graphs`, and `tests/architecture` |

## Migration boundaries

1. No existing V2 route is repurposed. The V3 API is mounted independently at
   `/api/v3`, so existing frontend flows remain stable.
2. Semantic routing in `router_agent.py` has a rule fallback and is explicitly
   forbidden from the V3 execution path.
3. V3 agents receive only their minimum state slice. Existing memory/history
   services may be called through read-only tools, never through globals.
4. Business records and durable graph checkpoints are separate stores. The
   initial V3 implementation uses SQLite for both local V3 business data and
   LangGraph checkpoints, with separate tables/paths.

## Phase 0 reflection / acceptance

- [x] Existing services were classified before deletions or rewrites.
- [x] Legacy semantic rule fallback is identified and isolated from V3.
- [x] Existing routes are preserved through an adapter-first migration.
- [x] Mock capability is explicitly demoted to demo mode for V3.

Result: **PASS**. It is safe to add the V3 runtime without deleting legacy code.
