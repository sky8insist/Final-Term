from app.schemas.critic import CriticIssue, CriticOutput


def test_failed_critic_output_projects_revision_targets_from_issues():
    issue = CriticIssue(issue_type="hallucination", target_agent="planning_agent", severity="high", message="Unsupported task")
    output = CriticOutput(passed=False, issues=[issue], confidence=.9)
    assert output.revision_targets == ["planning_agent"]


def test_failed_critic_output_normalizes_conflicting_projection_to_issue_target():
    issue = CriticIssue(issue_type="hallucination", target_agent="planning_agent", severity="high", message="Unsupported task")
    output = CriticOutput(passed=False, issues=[issue], revision_targets=["closure_agent"], confidence=.9)
    assert output.revision_targets == ["planning_agent"]
