from langgraph.graph import END, START, StateGraph

from app.agents.morning import morning_node
from app.state.dayend_state import DayendState


def build_morning_graph(*, with_checkpointer: bool = False):
    graph = StateGraph(DayendState)
    graph.add_node("morning", morning_node)
    graph.add_edge(START, "morning")
    graph.add_edge("morning", END)
    return graph.compile(checkpointer=None)
