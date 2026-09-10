from app.graphs.routing import route_supervisor_result
from app.schemas.common import AgentEnvelope, AgentMeta
from app.schemas.supervisor import SupervisorOutput


def test_supervisor_routes_emotion_to_safety_path():
    envelope = AgentEnvelope(meta=AgentMeta(agent_name="supervisor_agent", run_id="r", model="test", attempt=1), data=SupervisorOutput(primary_intent="emotion_release", confidence=.8), confidence=.8)
    assert route_supervisor_result({"supervisor_result": envelope}) == "emotion"
