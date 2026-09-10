# Project Memory

Last updated: 2026-09-10 (Asia/Shanghai)

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

## Safety and repository rules

- Never print, copy, stage or commit `.env` values or provider keys.
- Runtime logs belong in `.run/`; SQLite test artifacts belong outside Git and tests must remove their own files.
- Do not restore removed compatibility routes, Workbench mock routes, synchronous exam/plan generation routes, or a public wrong-answer-book feature.
- Evidence must distinguish real calls, source tests and unrun targets. Missing metrics are `N/A`, never zero.

## Open work

1. Fine-grained V3 SSE plus authenticated frontend Activity Drawer and HITL confirmation UI.
2. Resolve the stalled full backend pytest run before treating it as a green gate.
3. Build the 100-case evaluation, A/B/C ablation and real metrics report.
4. Move durable checkpoint and business persistence to production PostgreSQL and verify server-restart recovery.
