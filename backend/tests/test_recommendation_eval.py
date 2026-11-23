import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.services.recommendation_eval_service import audit_recommendations, evaluate_recommendation_cases
from app.services.recommendation_service import build_recommendations

DATASET = json.loads((Path(__file__).resolve().parents[1] / "evals/recommendation_cases.json").read_text(encoding="utf-8"))


def case_named(name):
    return deepcopy(next(case for case in DATASET["cases"] if case["id"] == name))


def single(case):
    return {"datasetVersion": DATASET["datasetVersion"], "cases": [case]}


@pytest.mark.parametrize("case", DATASET["cases"], ids=lambda case: case["id"])
def test_labelled_policy_regression(case):
    report = evaluate_recommendation_cases(single(case))
    assert report["passed"], report["cases"][0]["failures"]


@pytest.mark.parametrize("reason", ["当前掌握度 99%", "复习已到期", "近期高信心答错，建议纠正概念理解",
                                   "闪卡回忆失败，需要重新评估", "模型认为你应该复习"])
def test_auditor_rejects_fabricated_claim_without_using_scorer(reason):
    case = case_named("no-evidence-learn")
    result = {"actions": [{"id": "a", "subjectId": "s", "knowledgePointId": "a", "actionType": "tutor",
                           "href": "/guided-study?topicId=a", "reasons": [reason]}]}
    audit = audit_recommendations(case["snapshot"], result, now=datetime.fromisoformat(case["now"]))
    assert audit["claims"][0]["supported"] is False
    assert audit["violations"][0]["kind"] == "unsupported_reason"


def test_wrong_exam_days_and_target_are_rejected():
    case = case_named("near-exam-scoped-topic-first")
    now = datetime.fromisoformat(case["now"])
    result = build_recommendations(**case["snapshot"], now=now)
    result["actions"][0]["reasons"][0] = "e：今天考试，本知识点在考试范围内"
    result["actions"][0]["href"] = "/guided-study?topicId=foreign&examEventId=e"
    violations = audit_recommendations(case["snapshot"], result, now=now)["violations"]
    assert {row["kind"] for row in violations} == {"target", "unsupported_reason"}


def test_cross_subject_event_cannot_support_even_matching_reason_text():
    case = case_named("cross-subject-exam-map-rejected")
    now = datetime.fromisoformat(case["now"])
    result = build_recommendations(**case["snapshot"], now=now)
    action = next(row for row in result["actions"] if row["id"] == "a")
    action["href"] += "&examEventId=e"
    action["reasons"].append("e：3 天后考试，本知识点在考试范围内")
    audit = audit_recommendations(case["snapshot"], result, now=now)
    assert any(row["kind"] == "scope" for row in audit["violations"])
    assert audit["claims"][-1]["supported"] is False


def test_gate_fails_when_required_risk_reason_is_omitted():
    case = case_named("flashcard-failure-remains-visible")
    def omit_risk(**kwargs):
        result = build_recommendations(**kwargs)
        result["actions"][0]["reasons"] = [reason for reason in result["actions"][0]["reasons"] if "闪卡" not in reason]
        return result
    report = evaluate_recommendation_cases(single(case), predictor=omit_risk)
    assert report["metrics"]["reasonFaithfulness"] == 1
    assert not report["passed"]  # Faithful statements alone do not guarantee a complete explanation.
    assert any(row["kind"] == "required_reason" for row in report["cases"][0]["failures"])


def test_top1_metric_detects_reversed_rank():
    def reversed_rank(**kwargs):
        result = build_recommendations(**kwargs)
        result["actions"].reverse()
        return result
    report = evaluate_recommendation_cases(single(case_named("weaker-objective-evidence-first")), predictor=reversed_rank)
    assert report["metrics"]["top1HitRate"] == 0
    assert report["metrics"]["reasonFaithfulness"] == 1
    assert not report["passed"]


def test_empty_claims_are_na_and_missing_reasons_fail():
    case = case_named("no-evidence-learn")
    def no_reasons(**kwargs):
        result = build_recommendations(**kwargs)
        result["actions"][0]["reasons"] = []
        return result
    report = evaluate_recommendation_cases(single(case), predictor=no_reasons)
    assert report["metrics"]["reasonFaithfulness"] is None
    assert not report["passed"]
    report = evaluate_recommendation_cases(single(case_named("mastered-not-due-abstain")))
    assert report["passed"] and report["metrics"]["top1HitRate"] is None
    assert report["metrics"]["abstentionAccuracy"] == 1


def test_foreign_and_duplicate_actions_fail_scope_and_uniqueness():
    case = case_named("no-evidence-learn")
    def leak(**kwargs):
        result = build_recommendations(**kwargs)
        action = deepcopy(result["actions"][0])
        action.update(id="foreign", knowledgePointId="foreign", subjectId="outside")
        result["actions"].extend([action, action])
        return result
    report = evaluate_recommendation_cases(single(case), predictor=leak)
    assert report["metrics"]["snapshotScopeConsistency"] == 0
    assert {issue["kind"] for issue in report["cases"][0]["failures"]} >= {"scope", "duplicate"}


def test_determinism_gate_detects_unsorted_tasks():
    case = case_named("tasks-stable-over-page-limit")
    def unsorted_tasks(**kwargs):
        result = build_recommendations(**kwargs)
        result["todayTasks"] = kwargs["tasks"][:10]
        return result
    report = evaluate_recommendation_cases(single(case), predictor=unsorted_tasks)
    assert report["metrics"]["determinismRate"] == 0
    assert not report["passed"]


@pytest.mark.parametrize("mutation,match", [
    (lambda dataset: dataset.update(cases=[]), "nonempty"),
    (lambda dataset: dataset["cases"].append(deepcopy(dataset["cases"][0])), "Duplicate"),
    (lambda dataset: dataset["cases"][0].update(now="2026-10-08T00:00:00"), "timezone"),
    (lambda dataset: dataset["cases"][0].update(expectedTop1Ids=["foreign"]), "eligible"),
    (lambda dataset: dataset["cases"][0].update(limit=0), "limit"),
    (lambda dataset: dataset["cases"][0]["snapshot"].pop("tasks"), "seven"),
    (lambda dataset: dataset["cases"][0].update(requiredTop1ReasonCodes=["unknown"]), "unknown"),
])
def test_invalid_labels_are_errors(mutation, match):
    dataset = single(case_named("no-evidence-learn"))
    mutation(dataset)
    with pytest.raises(ValueError, match=match):
        evaluate_recommendation_cases(dataset)
