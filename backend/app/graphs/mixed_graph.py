"""LangGraph fan-out/fan-in workflow for mixed end-of-day inputs."""

from langgraph.graph import END, START, StateGraph

from app.agents.closure import closure_node
from app.agents.critic import critic_node
from app.agents.emotion import emotion_node
from app.agents.planner import planning_node
from app.agents.safety import safety_node
from app.state.dayend_state import DayendState


def fan_out_specialists(_: DayendState) -> list[str]:
    """Run independent semantic specialists concurrently; graph edges preserve dependencies."""
    return ["closure", "emotion"]


def build_mixed_graph(*, with_checkpointer: bool = False):
    graph = StateGraph(DayendState)
    graph.add_node("closure", closure_node)
    graph.add_node("planning", planning_node)
    graph.add_node("emotion", emotion_node)
    graph.add_node("safety", safety_node)
    graph.add_node("critic", critic_node)
    graph.add_conditional_edges(START, fan_out_specialists, {"closure": "closure", "emotion": "emotion"})
    graph.add_edge("closure", "planning")
    graph.add_edge("emotion", "safety")
    graph.add_edge(["planning", "safety"], "critic")
    graph.add_edge("critic", END)
    return graph.compile(checkpointer=None)
