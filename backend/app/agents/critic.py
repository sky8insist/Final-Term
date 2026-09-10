import json

from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.critic import CriticOutput
from app.state.dayend_state import DayendState


PROMPT = """You are the Critic Agent. Semantically review the supplied original evidence and
specialist outputs for grounding, unsupported inference, missing information, role violations,
contradictions, and actionability. Do not change any specialist output. If passed is false, you
must emit at least one issue and list every affected issue target in revision_targets. Return the
CriticOutput schema."""


async def critic_node(state: DayendState) -> dict:
    def serialized_result(name: str):
        result = state.get(name)
        if result is None:
            return None
        data = result.data if hasattr(result, "data") else result
        return data.model_dump(mode="json") if hasattr(data, "model_dump") else data

    payload = {
        "user_input": state["user_input"],
        "closure_result": serialized_result("closure_result"),
        "planning_result": serialized_result("planning_result"),
        "emotion_result": serialized_result("emotion_result"),
        "safety_result": serialized_result("safety_result"),
    }
    envelope, trace = await invoke_structured_agent(
        agent_name="critic_agent", schema=CriticOutput, system_prompt=PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False), run_id=state["run_id"],
        input_refs=[key for key, value in payload.items() if value is not None],
    )
    return {"critic_result": envelope, "agent_trace": [trace]}
