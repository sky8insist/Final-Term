from langgraph.graph import END, START, StateGraph

from app.agents.supervisor import supervisor_node
from app.agents.closure import closure_node
from app.agents.planner import planning_node
from app.agents.critic import critic_node
from app.agents.emotion import emotion_node
from app.agents.safety import safety_node
from app.graphs.revision import prepare_revision, route_after_critic, route_after_revision
from app.graphs.human import human_confirmation_node, needs_human_confirmation
from app.graphs.routing import route_supervisor_result
from app.graphs.mixed_graph import build_mixed_graph
from app.graphs.morning_graph import build_morning_graph
from app.graphs.persistence import persistence_node
from app.persistence.checkpointer import get_dayend_checkpointer
from app.state.dayend_state import DayendState


def build_closure_graph(*, checkpointer=None):
    graph = StateGraph(DayendState)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("closure", closure_node)
    graph.add_node("planning", planning_node)
    graph.add_node("critic", critic_node)
    graph.add_node("prepare_revision", prepare_revision)
    graph.add_node("human_confirmation", human_confirmation_node)
    graph.add_node("emotion", emotion_node)
    graph.add_node("safety", safety_node)
    # The root owns durability. Child graphs receive the same shared state and
    # execute as genuine LangGraph subgraphs, not placeholder routing nodes.
    graph.add_node("mixed", build_mixed_graph(with_checkpointer=False))
    graph.add_node("morning", build_morning_graph(with_checkpointer=False))
    graph.add_node("human_review", lambda _: {"final_output": {"status": "human_review_required"}})
    graph.add_node("persistence", persistence_node)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_supervisor_result, {
        "closure": "closure", "emotion": "emotion", "mixed": "mixed",
        "morning": "morning", "human_review": "human_review",
    })
    graph.add_conditional_edges("closure", needs_human_confirmation, {
        "human_confirmation": "human_confirmation", "planning": "planning",
    })
    graph.add_edge("human_confirmation", "planning")
    graph.add_edge("planning", "critic")
    graph.add_edge("emotion", "safety")
    graph.add_edge("safety", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"end": "persistence", "prepare_revision": "prepare_revision"})
    graph.add_conditional_edges("prepare_revision", route_after_revision, {
        "closure": "closure", "planning": "planning", "emotion": "emotion",
        "safety": "safety", "human_review": "human_review",
    })
    graph.add_edge("human_review", "persistence")
    graph.add_edge("mixed", "persistence")
    graph.add_edge("morning", "persistence")
    graph.add_edge("persistence", END)
    return graph.compile(checkpointer=checkpointer)


async def build_persistent_closure_graph():
    return build_closure_graph(checkpointer=await get_dayend_checkpointer())


build_phase_one_graph = build_closure_graph
