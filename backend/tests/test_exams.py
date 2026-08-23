import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app
from app.services import exam_service

client = TestClient(app)


def test_exam_routes_require_login():
    assert client.get("/api/v1/exams?subject_id=s").status_code == 401
    assert client.post("/api/v1/exams/attempts", json={"examId": "exam"}).status_code == 401
    assert client.post("/api/v1/exams/attempts/a/submit").status_code == 401
    assert client.get("/api/v1/exam-attempts/history?subject_id=s").status_code == 401
    assert client.post("/api/v1/exam-attempts/a/questions/q/confirm", json={"response": "A"}).status_code == 401
    assert client.get("/api/v1/exams/e/export").status_code == 401


def test_exam_exports_markdown_and_pdf(monkeypatch):
    monkeypatch.setattr(exam_service, "get_exam", lambda **_: {
        "title": "阶段测试：第三章", "duration_minutes": 30, "total_points": 10,
        "questions": [{
            "stem": "矩阵可逆的条件是什么？", "points": 10, "options": [],
            "correctAnswer": "行列式不为零", "explanation": "等价条件",
        }],
    })
    markdown, media_type, filename = exam_service.export_exam(
        user_id="u", exam_id="e", export_format="markdown",
    )
    assert "阶段测试".encode() in markdown
    assert media_type.startswith("text/markdown")
    assert filename.endswith(".md")
    pdf, media_type, filename = exam_service.export_exam(
        user_id="u", exam_id="e", export_format="pdf",
    )
    assert pdf.startswith(b"%PDF")
    assert media_type == "application/pdf"
    assert filename.endswith(".pdf")


@pytest.mark.parametrize(
    ("response", "answer", "correct"),
    [("A", "a", True), (["B", "A"], ["a", "b"], True), ("错", "对", False)],
)
def test_objective_grading_is_deterministic(response, answer, correct):
    result = exam_service.grade_objective(
        question_type="single_choice", response=response, correct_answer=answer, points=5,
    )
    assert result["isCorrect"] is correct
    assert result["earnedPoints"] == (5 if correct else 0)


@pytest.mark.parametrize(
    ("response", "answers", "correct"),
    [(" 长期 方向 ", ["长期方向", "长期发展方向"], True),
     ("长期发展方向", ["长期方向", "长期发展方向"], True),
     ("短期排班", ["长期方向", "长期发展方向"], False)],
)
def test_fill_blank_accepts_normalized_aliases(response, answers, correct):
    result = exam_service.grade_objective(
        question_type="fill_blank", response=response, correct_answer=answers, points=2,
    )
    assert result["isCorrect"] is correct


def test_short_answer_requires_fixed_rubric_matching_points():
    question = {
        "questionType": "short_answer", "stem": "战略为什么需要资源配置？",
        "options": [], "correctAnswer": "资源配置支撑长期目标与行动方案。",
        "explanation": "答案需连接目标、行动与资源。", "citationIds": ["c1"],
        "rubric": {"criteria": [
            {"description": "说明资源支撑长期目标", "points": 3},
            {"description": "说明资源与行动方案的关系", "points": 2},
        ]},
    }
    assert exam_service._validate_generated_questions(
        {"questions": [question]},
        [{"questionType": "short_answer", "count": 1, "pointsEach": 5}],
        {"c1"},
    ) == [question]
    question["rubric"]["criteria"][1]["points"] = 1
    with pytest.raises(HTTPException):
        exam_service._validate_generated_questions(
            {"questions": [question]},
            [{"questionType": "short_answer", "count": 1, "pointsEach": 5}],
            {"c1"},
        )


def test_generated_questions_must_match_blueprint():
    result = {"questions": [{
        "questionType": "single_choice", "stem": "1+1?", "options": ["1", "2"],
        "correctAnswer": "2", "explanation": "加法", "citationIds": ["c1"],
    }]}
    assert len(exam_service._validate_generated_questions(
        result, [{"questionType": "single_choice", "count": 1, "pointsEach": 2}],
        {"c1"},
    )) == 1
    with pytest.raises(HTTPException):
        exam_service._validate_generated_questions(
            result, [{"questionType": "single_choice", "count": 2, "pointsEach": 2}],
            {"c1"},
        )


def test_duplicate_questions_are_rejected():
    question = {
        "questionType": "true_false", "stem": "矩阵一定可逆", "correctAnswer": False,
        "explanation": "奇异矩阵不可逆", "citationIds": ["c1"],
    }
    with pytest.raises(HTTPException):
        exam_service._validate_generated_questions(
            {"questions": [question, dict(question)]},
            [{"questionType": "true_false", "count": 2, "pointsEach": 1}],
            {"c1"},
        )


def test_semantically_near_duplicate_questions_are_rejected():
    first = {
        "questionType": "true_false", "stem": "判断矩阵 A 是否一定可逆",
        "correctAnswer": False, "explanation": "不一定", "citationIds": ["c1"],
    }
    second = {
        **first, "stem": "请判断：矩阵 A 是否一定可逆？",
    }
    with pytest.raises(HTTPException):
        exam_service._validate_generated_questions(
            {"questions": [first, second]},
            [{"questionType": "true_false", "count": 2, "pointsEach": 1}],
            {"c1"},
        )


def test_generated_questions_reject_invented_citations():
    result = {"questions": [{
        "questionType": "true_false", "stem": "矩阵可以相乘", "correctAnswer": True,
        "explanation": "维度满足时可以", "citationIds": ["invented"],
    }]}
    with pytest.raises(HTTPException):
        exam_service._validate_generated_questions(
            result, [{"questionType": "true_false", "count": 1, "pointsEach": 1}], {"real"},
        )
