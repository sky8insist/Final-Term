# Dayend V3 Acceptance Record

This record reflects automated tests and the explicitly listed real acceptance
evidence. It does not convert unrun quality targets into passes.

| Gate | Evidence | Status |
|---|---|---|
| Independent structured invocation | `test_agent_invocations.py` | Pass |
| Closure → Planning dependency | `test_planner.py` | Pass |
| Critic revision bound | `test_revision_loop.py` | Pass |
| HITL durable resume | `test_interrupt_resume.py` | Pass |
| Mixed parallel DAG | `test_mixed_graph.py` | Pass |
| Tool isolation | `test_tool_permissions.py` | Pass |
| V3 API surface | `test_v3_api_contract.py` | Pass |
| Seven real structured invocations | `.run/dayend-live-all.stdout.log`, Critic retry log | Pass |
| Real Mixed graph | `.run/dayend-mixed.stdout.log` | Pass |
| Real Critic → Planning revision → Critic | `.run/dayend-revision-tracecomplete.stdout.log` | Pass |
| Real checkpoint resume | `.run/dayend-hitl-statefix.stdout.log` | Pass |
| Full backend regression | `198 passed, 3 warnings` in 366.54s | Pass |
| Real multi-agent smoke | Mixed graph: 5 structured calls with provider token usage | Pass |
| Real Critic revision | Critic → Planning revision → Critic, revision count 1 | Pass |
| Real 100-case A/B/C runtime batch | 300/300 records, 0 failures; `.run/dayend-ablation-full-report.json` | Pass (runtime only) |
| Scorable A/B/C batch | 300 unique successful outputs; one failed attempt retried and retained | Pass |
| Blind-review export | Two independent 300-item packets in `.run/dayend-blind-review/` | Pass |
| Authenticated V3 HTTP stream and ownership isolation | Local real-provider SSE: owner `GET` 200; another user `GET`/`resume` 404 | Pass |
| SSE interruption semantics | `confirmation_required` no longer emits a contradictory `run_completed`; regression covered by `test_dayend_run_service.py` | Pass |
| Full backend regression after stream semantics fix | `202 passed, 3 warnings` in 18.84s | Pass |

The authenticated API stream and its ownership controls have real acceptance evidence.
The Activity Drawer and HITL confirmation rendering still need live-browser acceptance.
The stream emits role-start, role-completion, confirmation-required,
controlled-failure and completion events; an interrupted stream does not claim completion.
On 2026-09-13, local Supabase PostgreSQL migration 028, cross-process checkpoint
resume and JSONB business-projection recovery passed; Windows PostgreSQL startup
also passed after selecting the psycopg-compatible Selector event loop.

## Delivery decision — 2026-09-13

The delivery owner cannot obtain the two independent blind-review score files.
Accordingly, this delivery is **limited technical acceptance**: runtime, API,
security and persistence evidence may be used, while A/B/C quality and currency
cost results are explicitly **N/A (quality review not completed)**. The blinded
packets and private answer key remain retained for a future independent review.
No automated score, coordinator score or inferred result may replace the missing
independent reviews. Browser-driven Activity Drawer/HITL acceptance also remains
open and is not included in this limited-acceptance conclusion.
