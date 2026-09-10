import asyncio
from datetime import datetime, timezone

from app.agents import critic
from app.schemas.common import AgentEnvelope, AgentMeta, AgentTrace
from app.schemas.critic import CriticOutput
from app.schemas.emotion import EmotionReflection
from app.schemas.safety import SafetyAssessment


def _envelope(name, data):
    return AgentEnvelope(meta=AgentMeta(agent_name=name, run_id="r1", model="test", attempt=1), data=data, confidence=.9)


def test_critic_serializes_validated_emotion_and_safety_results(monkeypatch):
    async def fake_invoke(**kwargs):
        assert '"reflection_summary": "stress"' in kwargs["user_prompt"]
        assert '"level": "low"' in kwargs["user_prompt"]
        output = CriticOutput(passed=True, confidence=.9)
        trace = AgentTrace(agent="critic_agent", started_at=datetime.now(timezone.utc), ended_at=datetime.now(timezone.utc), duration_ms=1, attempt=1, input_refs=[], output_schema="CriticOutput", status="success")
        return _envelope("critic_agent", output), trace

    monkeypatch.setattr(critic, "invoke_structured_agent", fake_invoke)
    emotion = _envelope("emotion_agent", EmotionReflection(reflection_summary="stress", confidence=.9))
    safety = _envelope("safety_agent", SafetyAssessment(level="low", immediate_response_required=False, suppress_delayed_only_response=False, response_strategy="supportive", confidence=.9))
    result = asyncio.run(critic.critic_node({"run_id": "r1", "user_input": "今天很焦虑", "emotion_result": emotion, "safety_result": safety}))
    assert result["critic_result"].data.passed is True
