import sqlite3
from pathlib import Path
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import START, StateGraph
from langgraph.types import Command, interrupt


def test_interrupt_resume_is_durable_across_graph_instances():
    data_dir = Path("data/dayend")
    data_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = data_dir / f"test-interrupt-{uuid4().hex}.sqlite"
    stores = []

    def ask(state):
        answer = interrupt({"question": "confirm?"})
        return {"answer": answer}

    def graph_with_store():
        store = SqliteSaver(sqlite3.connect(checkpoint_file, check_same_thread=False))
        stores.append(store)
        graph = StateGraph(dict)
        graph.add_node("ask", ask)
        graph.add_edge(START, "ask")
        return graph.compile(checkpointer=store)

    try:
        config = {"configurable": {"thread_id": "durable-thread"}}
        first = graph_with_store().invoke({}, config)
        assert "__interrupt__" in first
        resumed = graph_with_store().invoke(Command(resume={"confirmed": True}), config)
        assert resumed["answer"] == {"confirmed": True}
    finally:
        for store in stores:
            store.conn.close()
        checkpoint_file.unlink(missing_ok=True)
