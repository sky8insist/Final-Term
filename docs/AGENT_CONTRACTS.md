# Dayend V3 Agent Contracts

Every invocation returns `AgentEnvelope[T]` containing agent metadata, a schema
version, model name, attempt, and validated data.

| Agent | Contract | Input boundary |
|---|---|---|
| Supervisor | `SupervisorOutput` | User input, entry point, minimal session summary |
| Closure | `ClosureOutput` | User input |
| Planning | `PlanningOutput` | `ClosureOutput` only |
| Emotion | `EmotionReflection` | User input |
| Safety | `SafetyAssessment` | User input, Emotion output, deterministic guard |
| Critic | `CriticOutput` | Original input and specialist outputs |
| Morning | `MorningOutput` | Persisted night state |

Agents do not write business data. Persistence happens outside the agent runtime.
