# Dayend V3 real-evaluation contract

The 100 cases are collected before execution: 30 closure, 25 emotion, 20 mixed,
10 uncertain, 10 edge/conflict and 5 safety-critical cases. They must be
de-identified, assigned immutable `case_id`s and reviewed before provider calls.

`scripts/generate_dayend_eval_cases.py` produces a same-sized **synthetic**
fixture only for pipeline validation. It must not be used to claim user-study,
production or real-provider quality results.

Each case runs three variants: `single_agent`, `multi_agent_without_critic` and
`full_multi_agent`. A result JSONL row has `case_id`, `variant`,
`simulated: false`, real provider trace references, and judge/measurement fields
`grounding`, `unsupported_task_rate`, `actionability`, `latency_ms` and
`token_cost`. Missing provider usage remains `null`; it is rendered as `N/A`.

Generate a report only from real records:

```powershell
python scripts/summarize_dayend_evaluation.py .run/dayend-eval.jsonl --output .run/dayend-eval-report.json
```
