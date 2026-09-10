from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.emotion import EmotionReflection
from app.state.dayend_state import DayendState

PROMPT = """You are the Emotion Reflection Specialist, not a therapist. Extract explicit events,
emotions, and unresolved thoughts. Keep every inference separate in inferred_content; do not
diagnose, infer personality, or offer treatment. Return EmotionReflection."""


async def emotion_node(state: DayendState) -> dict:
    feedback = (state.get("critic_feedback") or {}).get("emotion_agent", [])
    envelope, trace = await invoke_structured_agent(agent_name="emotion_agent", schema=EmotionReflection,
        system_prompt=PROMPT, user_prompt=state["user_input"] + ("\n\nCritic revision feedback:\n- " + "\n- ".join(feedback) if feedback else ""),
        run_id=state["run_id"], input_refs=["user_input"] + (["critic_feedback"] if feedback else []))
    if feedback:
        trace = trace.model_copy(update={"status": "revision"})
    return {"emotion_result": envelope, "agent_trace": [trace]}
