# Project Memory

Last updated: 2026-09-13 (Asia/Shanghai)

Current project-wide acceptance index: `docs/acceptance/CURRENT_PROJECT_ACCEPTANCE_20260913.md`
(`2026-09-13`, conditional local technical acceptance; not production-final acceptance).

## Durable facts

- Dayend V3 is isolated at `/api/v3`; existing learning APIs remain under `/api/v1`.
- Multi-agent mode uses SiliconFlow through the existing OpenAI-compatible configuration. It must never silently fall back to semantic rules.
- The seven roles are Supervisor, Closure, Planning, Emotion, Safety, Critic and Morning. Agent outputs are Pydantic contracts and traces retain latency, attempts and provider token usage when available.
- Root graphs execute asynchronously. Durable checkpoints must use `AsyncSqliteSaver`; synchronous `SqliteSaver` is incompatible with `ainvoke`.
- Critic graph routing is projected from each issue's explicit `target_agent`. This is contract normalization, not a semantic fallback.

## Verified evidence

- All seven agents have completed at least one real structured SiliconFlow invocation.
- Real Mixed graph and Critic → Planning revision → Critic flows have been verified.
- Real HITL has been verified across a SQLite checkpoint and a newly created graph instance.
- Full backend pytest completed after isolating assistant unit tests from real
  conversation-context and dialogue-classification services: `198 passed, 3 warnings`
  in 366.54 seconds on 2026-09-10.
- Real `DAYEND_MODE=multi_agent` smoke and Critic→Planning revision smoke both
  passed with provider token usage recorded in `.run/dayend-real-*.stdout.log`.
- Real A/B/C runtime batch completed: 300/300 records with zero failures. Mean
  latency/token totals are in `.run/dayend-ablation-full-report.json`; independent
  quality scores and currency cost remain N/A pending source evidence.
- A scorable rerun completed with 300 unique successful outputs. One rejected
  Planning source reference was retried successfully; its failed attempt remains
  in the JSONL audit trail. Two 300-item blinded reviewer packets are under
  `.run/dayend-blind-review/`.
- On 2026-09-12, a real authenticated V3 SSE request passed with owner access
  returning 200 and a second local user receiving 404 for both read and resume.
  The real stream did not request confirmation for either tested semantic input;
  it must not be represented as a live UI confirmation acceptance.
- A stream interrupted for confirmation no longer emits `run_completed`; the
  focused tests and full backend regression passed at `202 passed, 3 warnings`.
- ClosureOutput now requires every model-classified `uncertain` item to name an
  existing confirmation id. A real direct Closure call produced one uncertain
  item and one pending confirmation on 2026-09-12; a full root-graph run with
  the same input may still classify it differently, so browser HITL acceptance
  remains unverified. The latest full regression is `205 passed, 3 warnings`.
- Blind review now keeps the A/B/C mapping in private answer keys and merges it
  only after independent reviewers submit `review_id`-based JSONL scores. The
  export/merge/validation tooling is tested. On 2026-09-13, the delivery owner
  confirmed that two independent reviewer returns cannot be obtained; quality
  and currency-cost conclusions are therefore explicitly `N/A (quality review
  not completed)`, never inferred or automated.
- PostgreSQL persistence implementation is prepared behind
  `DAYEND_PERSISTENCE_BACKEND=postgres`: checkpoints use AsyncPostgresSaver and
  business projections use JSONB tables from migration 028. SQLite remains the
  active compatibility path by default. On 2026-09-13, local Supabase migration
  028 schema, PostgreSQL checkpoint restart/resume, and JSONB business-projection
  recovery were verified. Windows PostgreSQL startup uses a Selector event-loop
  compatibility layer because psycopg async is incompatible with Proactor.
- Real full E2E `acceptance-20260913T205814-live` completed on 2026-09-13:
  43/46 checks passed. Real PDF ingestion, auth isolation, chat, artifacts
  (including mind map), exam/grading, planning and privacy cleanup passed.
  Retrieval remains the functional gate: Chandler direct retrieval plus the
  Andrews and Johnson Golden cases missed; Recall@5 is 18/20 (0.90).

## Safety and repository rules

- Never print, copy, stage or commit `.env` values or provider keys.
- Runtime logs belong in `.run/`; SQLite test artifacts belong outside Git and tests must remove their own files.
- Do not restore removed compatibility routes, Workbench mock routes, synchronous exam/plan generation routes, or a public wrong-answer-book feature.
- Evidence must distinguish real calls, source tests and unrun targets. Missing metrics are `N/A`, never zero.

## Open work

1. Complete live-browser acceptance for the authenticated V3 Activity Drawer and HITL confirmation flow. The authenticated API stream and ownership controls have real acceptance evidence; the drawer still needs a browser-driven confirmation/resume rendering check.
2. If independent reviewer JSONL becomes available in the future, merge and validate it with the private answer key. This is outside the current delivery; no automated quality value may replace it.
