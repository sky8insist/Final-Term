# Dayend V3 Multi-Agent Architecture

Dayend V3 is isolated at `/api/v3` and does not replace the existing exam-review API.
Its runtime uses LangGraph for shared state, routing, interrupts, checkpointing, and
streaming; LangChain/OpenAI-compatible models for each specialist invocation; and
Pydantic contracts for all agent outputs.

## Execution paths

- Closure: Supervisor → Closure → [human confirmation] → Planning → Critic.
- Emotion: Supervisor → Emotion → Safety → Critic.
- Mixed: Closure and Emotion fan out in parallel; Planning depends on Closure,
  Safety depends on Emotion; Critic waits for both branches.
- Morning: persisted night state → Morning Agent.

Critic returns issues to the named specialist; each target may revise at most two
times, then the run requires human review. Checkpoints are SQLite records under
`DAYEND_CHECKPOINT_PATH` and are intentionally separate from business data.

## Modes

`DAYEND_MODE=multi_agent` requires a model provider and exposes failures after
bounded retry. It does not use legacy semantic rule fallbacks. `demo` is reserved
for explicitly-labelled simulations and must never masquerade as an LLM trace.
