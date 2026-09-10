from app.agents import supervisor
from app.graphs.root_graph import build_phase_one_graph
from app.schemas.common import AgentEnvelope, AgentMeta, AgentTrace
from app.schemas.supervisor import SupervisorOutput


def test_phase_one_graph_runs_supervisor(monkeypatch):
    async def fake_node(state):
        return {
            "supervisor_result": AgentEnvelope(
                meta=AgentMeta(agent_name="supervisor_agent", run_id=state["run_id"], model="test", attempt=1),
                data=SupervisorOutput(primary_intent="unknown", confidence=0.8), confidence=0.8,
            ),
            "agent_trace": [AgentTrace.model_validate({
                "agent": "supervisor_agent", "started_at": "2026-01-01T00:00:00Z",
                "ended_at": "2026-01-01T00:00:00Z", "duration_ms": 1, "attempt": 1,
                "input_refs": [], "output_schema": "SupervisorOutput", "status": "success",
            })],
        }

    monkeypatch.setattr(supervisor, "supervisor_node", fake_node)
    # The graph imports the node at build time; this test verifies its compiled
    # topology separately from provider integration.
    graph = build_phase_one_graph()
    assert {"supervisor", "closure", "planning", "critic"} <= set(graph.get_graph().nodes)
