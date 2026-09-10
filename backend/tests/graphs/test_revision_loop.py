from app.graphs.revision import MAX_CRITIC_REVISIONS, prepare_revision, route_after_revision
from app.schemas.common import AgentEnvelope, AgentMeta
from app.schemas.critic import CriticIssue, CriticOutput


def _failed_critic():
    return AgentEnvelope(
        meta=AgentMeta(agent_name="critic_agent", run_id="r1", model="test", attempt=1),
        data=CriticOutput(passed=False, issues=[CriticIssue(issue_type="unsupported_inference", target_agent="planning_agent", severity="high", message="Unsupported plan")], revision_targets=["planning_agent"], confidence=.9), confidence=.9,
    )


def test_critic_feedback_returns_to_the_target_agent():
    update = prepare_revision({"critic_result": _failed_critic()})
    assert update["revision_target"] == "planning_agent"
    assert update["critic_feedback"]["planning_agent"] == ["Unsupported plan"]
    assert route_after_revision(update) == "planning"


def test_critic_loop_escalates_after_bound():
    update = prepare_revision({"critic_result": _failed_critic(), "revision_count": {"planning_agent": MAX_CRITIC_REVISIONS}})
    assert update["revision_target"] == "human_review"


def test_critic_can_return_to_safety_agent():
    critic = _failed_critic().model_copy(update={
        "data": CriticOutput(passed=False, issues=[CriticIssue(issue_type="missing_item", target_agent="safety_agent", severity="high", message="Assess urgency")], revision_targets=["safety_agent"], confidence=.9),
    })
    update = prepare_revision({"critic_result": critic})
    assert route_after_revision(update) == "safety"
