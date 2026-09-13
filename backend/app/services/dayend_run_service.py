from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from fastapi import HTTPException, status
from langgraph.types import Command

from app.graphs.root_graph import build_persistent_closure_graph
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
    graph = await build_persistent_closure_graph()
    state = await graph.ainvoke(_initial_state(request=request, user_id=user_id, run_id=run_id, thread_id=thread_id), _config(thread_id))
    return run_id, {"runId": run_id, "threadId": thread_id, "state": jsonable_encoder(state)}


def _assert_run_owner(*, state: dict, user_id: str) -> None:
    """Hide run existence when the authenticated user does not own it."""
    if state.get("user_id") != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dayend run not found")


async def get_run(*, thread_id: str, user_id: str) -> dict:
    snapshot = await (await build_persistent_closure_graph()).aget_state(_config(thread_id))
    if not snapshot.values:
        return {"threadId": thread_id, "status": "not_found"}
    _assert_run_owner(state=snapshot.values, user_id=user_id)
    return {"threadId": thread_id, "status": "interrupted" if snapshot.next else "completed", "state": jsonable_encoder(snapshot.values), "next": list(snapshot.next)}


async def resume_run(*, thread_id: str, response: dict, user_id: str) -> dict:
    graph = await build_persistent_closure_graph()
    snapshot = await graph.aget_state(_config(thread_id))
    if not snapshot.values:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dayend run not found")
    _assert_run_owner(state=snapshot.values, user_id=user_id)
    if not snapshot.next:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dayend run does not require confirmation")
    state = await graph.ainvoke(Command(resume=response), _config(thread_id))
    return {"threadId": thread_id, "state": jsonable_encoder(state)}


async def stream_run(*, request: DayendRunRequest, user_id: str):
    """Yield direct LangGraph update events; no frontend-only fake activity."""
    run_id, thread_id = str(uuid4()), request.thread_id or str(uuid4())
    graph = await build_persistent_closure_graph()
    yield {"event": "run_started", "data": {"runId": run_id, "threadId": thread_id}}
    interrupted = False
    try:
        async for update in graph.astream(_initial_state(request=request, user_id=user_id, run_id=run_id, thread_id=thread_id), _config(thread_id), stream_mode="updates"):
            for node_name, node_state in update.items():
                if node_name == "__interrupt__":
                    interrupt_value = node_state[0].value if isinstance(node_state, tuple) else node_state
                    yield {"event": "confirmation_required", "data": jsonable_encoder(interrupt_value)}
                    interrupted = True
                    continue
                yield {"event": "agent_started", "data": {"node": node_name}}
                traces = node_state.get("agent_trace", []) if isinstance(node_state, dict) else []
                if traces:
                    trace = jsonable_encoder(traces[-1])
                    yield {"event": "agent_completed" if trace["status"] != "failed" else "run_failed", "data": trace}
                else:
                    yield {"event": "graph_updated", "data": {"node": node_name}}
    except Exception as exc:
        yield {"event": "run_failed", "data": {"runId": run_id, "threadId": thread_id, "message": str(exc)}}
        return
    if not interrupted:
        yield {"event": "run_completed", "data": {"runId": run_id, "threadId": thread_id}}
