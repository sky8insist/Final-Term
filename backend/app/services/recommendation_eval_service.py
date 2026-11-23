"""Offline policy regression, not an estimate of learning effectiveness.

The reason auditor checks source snapshots directly; it does not call the
recommendation scorer or learner-state projection to validate their output.
"""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from app.services.recommendation_service import ALGORITHM_VERSION, build_recommendations

EVAL_VERSION = "recommendation-eval-v1"
INPUT_KEYS = {"subjects", "topics", "mastery", "coverage", "events", "mappings", "tasks"}


def _time(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def audit_recommendations(snapshot: dict, result: dict, *, now: datetime) -> dict:
    """Closed set of reason templates: new wording must explicitly add an auditor.

    Scope here means consistency with an already owner-scoped snapshot. Database
    authorization remains independently tested by the service/API tests.
    """
    today = now.astimezone(timezone(timedelta(hours=8))).date()
    subjects = {row["id"] for row in snapshot["subjects"]}
    topics = {row["id"]: row for row in snapshot["topics"]
              if row["subject_id"] in subjects and not row.get("archived")}
    mastery = {(row["subject_id"], row["knowledge_key"]): row for row in snapshot["mastery"]}
    events = {row["id"]: row for row in snapshot["events"]}
    violations, claims, action_ids = [], [], set()
    for action in result["actions"]:
        action_id, subject_id = action["id"], action["subjectId"]
        topic = topics.get(action.get("knowledgePointId"))
        setup = action.get("actionType") == "setup"
        in_scope = subject_id in subjects and (
            (setup and action_id == f"setup:{subject_id}" and action.get("knowledgePointId") is None
             and not any(row["subject_id"] == subject_id for row in topics.values()))
            or (not setup and topic is not None and topic["subject_id"] == subject_id and action_id == topic["id"]))
        if not in_scope:
            violations.append({"actionId": action_id, "kind": "scope"})
        if action_id in action_ids:
            violations.append({"actionId": action_id, "kind": "duplicate"})
        action_ids.add(action_id)
        row = mastery.get((subject_id, topic["knowledge_key"]), {}) if topic else {}
        meta = row.get("metadata") or {}
        valid = {}
        if setup and in_scope:
            valid["尚无课程知识点，请上传资料或添加课程结构"] = "setup"
        elif topic and in_scope:
            if int(meta.get("assessmentCount", 0)) < 3:
                valid["评估证据不足，先建立学习与诊断基线"] = "cold_start"
            else:
                valid[f"当前掌握度 {round(float(row.get('mastery', 0.5)) * 100)}%"] = "mastery"
            due = _time(row.get("next_review_at"))
            if due and due <= now:
                valid["复习已到期"] = "due"
            if float(meta.get("misconceptionRisk", 0)) >= 0.75:
                valid["近期高信心答错，建议纠正概念理解"] = "misconception"
            if meta.get("flashcardRecallRisk"):
                valid["闪卡回忆失败，需要重新评估"] = "recall_risk"
            query = parse_qs(urlparse(action.get("href", "")).query)
            if query.get("topicId") != [topic["id"]]:
                violations.append({"actionId": action_id, "kind": "target"})
            event_ids = query.get("examEventId", [])
            if event_ids:
                event = events.get(event_ids[0]) if len(event_ids) == 1 else None
                mapped = event and any(mapping["exam_event_id"] == event["id"]
                    and mapping["knowledge_point_id"] == topic["id"] and float(mapping["weight"]) > 0
                    for mapping in snapshot["mappings"])
                if (event and mapped and event["subject_id"] == subject_id and event.get("status") == "active"
                        and date.fromisoformat(event["exam_date"]) >= today):
                    days = (date.fromisoformat(event["exam_date"]) - today).days
                    when = "今天考试" if days == 0 else f"{days} 天后考试"
                    valid[f"{event['title']}：{when}，本知识点在考试范围内"] = "exam"
                else:
                    violations.append({"actionId": action_id, "kind": "scope", "field": "examEventId"})
        reasons = action.get("reasons", [])
        if not reasons:
            violations.append({"actionId": action_id, "kind": "missing_reasons"})
        if len(set(reasons)) != len(reasons):
            violations.append({"actionId": action_id, "kind": "duplicate_reason"})
        for reason in reasons:
            code = valid.get(reason)
            claims.append({"actionId": action_id, "reason": reason, "code": code, "supported": code is not None})
            if code is None:
                violations.append({"actionId": action_id, "kind": "unsupported_reason", "reason": reason})
    return {"claims": claims, "violations": violations}


def evaluate_recommendation_cases(dataset: dict, *, predictor=build_recommendations) -> dict:
    if dataset.get("datasetVersion") != "recommendation-cases-v1" or not dataset.get("cases"):
        raise ValueError("Expected a nonempty recommendation-cases-v1 dataset")
    case_ids, results = set(), []
    for case in dataset["cases"]:
        case_id = case["id"]
        if case_id in case_ids:
            raise ValueError(f"Duplicate case ID: {case_id}")
        case_ids.add(case_id)
        snapshot = case["snapshot"]
        if set(snapshot) != INPUT_KEYS or any(not isinstance(value, list) for value in snapshot.values()):
            raise ValueError(f"{case_id}: snapshot must contain all seven input lists")
        now = _time(case["now"])
        if now is None or datetime.fromisoformat(case["now"].replace("Z", "+00:00")).tzinfo is None:
            raise ValueError(f"{case_id}: now must have an explicit timezone")
        expected = case["expectedTop1Ids"]
        if not isinstance(expected, list) or any(not isinstance(value, str) for value in expected):
            raise ValueError(f"{case_id}: expectedTop1Ids must be a list of strings (empty means abstain)")
        eligible = {row["id"] for row in snapshot["topics"] if not row.get("archived")
                    and row["subject_id"] in {subject["id"] for subject in snapshot["subjects"]}}
        eligible.update(f"setup:{subject['id']}" for subject in snapshot["subjects"]
                        if not any(row["subject_id"] == subject["id"] and not row.get("archived")
                                   for row in snapshot["topics"]))
        if not set(expected) <= eligible or len(expected) != len(set(expected)):
            raise ValueError(f"{case_id}: expectedTop1Ids must be distinct eligible actions")
        codes = {"setup", "cold_start", "mastery", "due", "misconception", "recall_risk", "exam"}
        if not set(case.get("requiredTop1ReasonCodes", [])) <= codes:
            raise ValueError(f"{case_id}: unknown required reason code")
        limit = case.get("limit", 3)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10:
            raise ValueError(f"{case_id}: limit must be 1..10")
        actual = predictor(**deepcopy(snapshot), now=now, limit=limit)
        actions = actual["actions"]
        audit = audit_recommendations(snapshot, actual, now=now)
        first = actions[0]["id"] if actions else None
        hit = first in expected if expected else not actions
        issues = list(audit["violations"])
        if not hit:
            issues.append({"kind": "top1", "expected": expected, "actual": first})
        if actions and case.get("expectedActionType") and actions[0]["actionType"] != case["expectedActionType"]:
            issues.append({"kind": "action_type"})
        if len(actions) > limit:
            issues.append({"kind": "limit"})
        forbidden = set(case.get("forbiddenActionIds", []))
        if forbidden.intersection(row["id"] for row in actions):
            issues.append({"kind": "forbidden_action"})
        first_codes = {claim["code"] for claim in audit["claims"] if claim["actionId"] == first}
        missing = set(case.get("requiredTop1ReasonCodes", [])) - first_codes
        if missing:
            issues.append({"kind": "required_reason", "missing": sorted(missing)})
        # Reverse input order: output must not depend on DB enumeration order.
        permuted = predictor(**{key: list(reversed(deepcopy(value))) for key, value in snapshot.items()}, now=now, limit=limit)
        deterministic = actual == permuted
        if not deterministic:
            issues.append({"kind": "determinism"})
        results.append({"caseId": case_id, "group": case["group"], "expectedTop1Ids": expected,
                        "actualTop1Id": first, "top1Hit": hit, "deterministic": deterministic,
                        "actions": actions, "claims": audit["claims"], "failures": issues})
    claims = [claim for row in results for claim in row["claims"]]
    selected = [row for row in results if row["expectedTop1Ids"]]
    abstentions = [row for row in results if not row["expectedTop1Ids"]]
    metrics = {
        "caseCount": len(results), "selectionCaseCount": len(selected), "abstentionCaseCount": len(abstentions),
        "top1HitRate": sum(row["top1Hit"] for row in selected) / len(selected) if selected else None,
        "abstentionAccuracy": sum(row["top1Hit"] for row in abstentions) / len(abstentions) if abstentions else None,
        "reasonClaimCount": len(claims), "supportedReasonClaimCount": sum(claim["supported"] for claim in claims),
        "reasonFaithfulness": sum(claim["supported"] for claim in claims) / len(claims) if claims else None,
        "snapshotScopeConsistency": sum(not any(issue["kind"] in {"scope", "forbidden_action"}
            for issue in row["failures"]) for row in results) / len(results),
        "determinismRate": sum(row["deterministic"] for row in results) / len(results),
    }
    return {"evaluationVersion": EVAL_VERSION, "datasetVersion": dataset["datasetVersion"],
            "algorithmVersion": ALGORITHM_VERSION,
            "scope": "synthetic offline policy regression; not real-user recommendation quality or DB isolation",
            "metrics": metrics, "groups": {group: {"caseCount": len(rows),
                "policyPassRate": sum(not row["failures"] for row in rows) / len(rows)}
                for group in sorted({row["group"] for row in results})
                for rows in [[row for row in results if row["group"] == group]]},
            "passed": all(not row["failures"] for row in results), "cases": results}
