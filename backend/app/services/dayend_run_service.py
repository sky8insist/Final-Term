from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from langgraph.types import Command

from app.graphs.root_graph import build_closure_graph
from app.models.dayend import DayendRunRequest


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _initial_state(*, request: DayendRunRequest, user_id: str, run_id: str, thread_id: str) -> dict:
    return {"thread_id": thread_id, "run_id": run_id, "user_id": user_id, "user_input": request.user_input,
            "entry_point": request.entry_point, "timestamp": datetime.now(timezone.utc).isoformat(),
            "current_session_summary": request.session_summary, "revision_count": {}, "critic_feedback": {},
            "pending_confirmation": [], "agent_trace": []}


async def create_run(*, request: DayendRunRequest, user_id: str) -> tuple[str, dict]:
    run_id, thread_id = str(uuid4()), request.thread_id or str(uuid4())
    graph = build_closure_graph()
    state = await graph.ainvoke(_initial_state(request=request, user_id=user_id, run_id=run_id, thread_id=thread_id), _config(thread_id))
    return run_id, {"runId": run_id, "threadId": thread_id, "state": jsonable_encoder(state)}


def get_run(*, thread_id: str) -> dict:
    snapshot = build_closure_graph().get_state(_config(thread_id))
    if not snapshot.values:
        return {"threadId": thread_id, "status": "not_found"}
    return {"threadId": thread_id, "status": "interrupted" if snapshot.next else "completed", "state": jsonable_encoder(snapshot.values), "next": list(snapshot.next)}


async def resume_run(*, thread_id: str, response: dict) -> dict:
    graph = build_closure_graph()
    state = await graph.ainvoke(Command(resume=response), _config(thread_id))
    return {"threadId": thread_id, "state": jsonable_encoder(state)}


async def stream_run(*, request: DayendRunRequest, user_id: str):
    """Yield direct LangGraph update events; no frontend-only fake activity."""
    run_id, thread_id = str(uuid4()), request.thread_id or str(uuid4())
    graph = build_closure_graph()
    yield {"event": "run_started", "data": {"runId": run_id, "threadId": thread_id}}
    async for update in graph.astream(_initial_state(request=request, user_id=user_id, run_id=run_id, thread_id=thread_id), _config(thread_id), stream_mode="updates"):
        for node_name, node_state in update.items():
            traces = node_state.get("agent_trace", []) if isinstance(node_state, dict) else []
            if traces:
                trace = jsonable_encoder(traces[-1])
                yield {"event": "agent_completed" if trace["status"] != "failed" else "run_failed", "data": trace}
            else:
                yield {"event": "graph_updated", "data": {"node": node_name}}
    yield {"event": "run_completed", "data": {"runId": run_id, "threadId": thread_id}}
