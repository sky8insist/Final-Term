import json

from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.morning import MorningOutput
from app.state.dayend_state import DayendState
from app.tools.morning_tools import get_confirmed_items, get_last_night_plan

PROMPT = """You are the Morning Agent. Use only last-night validated structured state and the
current context. Propose the smallest useful first action, surface blocked items, and keep any
emotion handoff optional. Do not summarize blindly or invent source item IDs. Return MorningOutput."""


async def morning_node(state: DayendState) -> dict:
    night = {"planning": state.get("planning_result"), "emotion": state.get("emotion_result"), "confirmation": state.get("human_response")}
    envelope, trace = await invoke_structured_agent(agent_name="morning_agent", schema=MorningOutput,
        system_prompt=PROMPT, user_prompt=json.dumps(night, ensure_ascii=False, default=str),
        run_id=state["run_id"], input_refs=["planning_result", "emotion_result", "human_response"],
        tools=[get_last_night_plan, get_confirmed_items])
    return {"final_output": {"morning": envelope.data.model_dump(mode="json")}, "agent_trace": [trace]}
