import json

from app.guardrails.safety import detect_urgent_signal
from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.safety import SafetyAssessment
from app.state.dayend_state import DayendState

PROMPT = """You are the Safety Agent. Assess risk based only on supplied user input, emotional
reflection, and deterministic guard result. Never diagnose. For urgent risk set level to urgent,
immediate_response_required and suppress_delayed_only_response to true, and use urgent_support.
Return SafetyAssessment."""


async def safety_node(state: DayendState) -> dict:
    guard = detect_urgent_signal(state["user_input"])
    emotion = state.get("emotion_result")
    payload = {"user_input": state["user_input"], "emotion": emotion.data.model_dump(mode="json") if emotion else None, "guard": guard}
    feedback = (state.get("critic_feedback") or {}).get("safety_agent", [])
    payload["critic_feedback"] = feedback
    envelope, trace = await invoke_structured_agent(agent_name="safety_agent", schema=SafetyAssessment,
        system_prompt=PROMPT, user_prompt=json.dumps(payload, ensure_ascii=False), run_id=state["run_id"],
        input_refs=["user_input", "emotion_result", "guardrail_result"] + (["critic_feedback"] if feedback else []))
    if feedback:
        trace = trace.model_copy(update={"status": "revision"})
    return {"guardrail_result": guard, "safety_result": envelope, "agent_trace": [trace]}
