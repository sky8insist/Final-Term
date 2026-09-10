from app.runtime.agent_factory import invoke_structured_agent
from app.schemas.supervisor import SupervisorOutput
from app.state.dayend_state import DayendState
from app.tools.session_tools import get_current_session_state, get_last_closure_status


SUPERVISOR_PROMPT = """You are Dayend's Supervisor Agent. Decide only the semantic route and an
ordered specialist execution plan. Do not extract tasks, plan tomorrow, provide emotional
advice, write data, or draft a final response. You must include Critic after every specialist
path. For emotion_release/mixed include Safety after Emotion. Return the supplied schema."""


async def supervisor_node(state: DayendState) -> dict:
    envelope, trace = await invoke_structured_agent(
        agent_name="supervisor_agent", schema=SupervisorOutput, system_prompt=SUPERVISOR_PROMPT,
        user_prompt=("user_input:\n" + state["user_input"] + "\nentry_point: " + state["entry_point"]
                     + "\nsession_summary: " + (state.get("current_session_summary") or "")),
        run_id=state["run_id"], input_refs=["user_input", "entry_point", "current_session_summary"],
        tools=[get_current_session_state, get_last_closure_status],
    )
    return {"supervisor_result": envelope, "agent_trace": [trace]}
