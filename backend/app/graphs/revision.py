from app.state.dayend_state import DayendState


MAX_CRITIC_REVISIONS = 2


def prepare_revision(state: DayendState) -> dict:
    critic = state.get("critic_result")
    if critic is None or critic.data.passed:
        return {"revision_target": None}
    targets = [target for target in critic.data.revision_targets if target in {
        "closure_agent", "planning_agent", "emotion_agent", "safety_agent",
    }]
    if not targets:
        return {"revision_target": "human_review"}
    target = targets[0]
    counts = dict(state.get("revision_count") or {})
    counts[target] = counts.get(target, 0) + 1
    if counts[target] > MAX_CRITIC_REVISIONS:
        return {"revision_count": counts, "revision_target": "human_review"}
    feedback = dict(state.get("critic_feedback") or {})
    feedback[target] = [issue.message for issue in critic.data.issues if issue.target_agent == target]
    return {"revision_count": counts, "critic_feedback": feedback, "revision_target": target}


def route_after_critic(state: DayendState) -> str:
    critic = state.get("critic_result")
    if critic and critic.data.passed:
        return "end"
    return "prepare_revision"


def route_after_revision(state: DayendState) -> str:
    target = state.get("revision_target")
    if target == "closure_agent":
        return "closure"
    if target == "planning_agent":
        return "planning"
    if target == "emotion_agent":
        return "emotion"
    if target == "safety_agent":
        return "safety"
    return "human_review"
