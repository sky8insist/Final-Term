from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_workbench_dashboard_contract():
    response = client.get("/api/workbench/dashboard")
    assert response.status_code == 200
    body = response.json()
    assert body["subjects"]
    assert set(body["stats"]) == {"studyMinutes", "completedTasks", "streakDays"}


def test_workbench_pages_have_placeholder_data():
    subject_id = client.get("/api/workbench/subjects").json()[0]["id"]
    assert client.get(f"/api/workbench/materials?subject_id={subject_id}").status_code == 200
    assert client.get(f"/api/workbench/chat/{subject_id}").status_code == 200
    assert client.get(f"/api/workbench/mind-map/{subject_id}").status_code == 200
    assert client.get(f"/api/workbench/exams/{subject_id}").status_code == 200
    assert client.get(f"/api/workbench/mistakes/{subject_id}").status_code == 200
    assert client.get(f"/api/workbench/plan?subject_id={subject_id}").status_code == 200


def test_workbench_chat_and_exam_placeholders():
    subject_id = client.get("/api/workbench/subjects").json()[0]["id"]
    chat = client.post("/api/workbench/chat", json={"subject_id": subject_id, "content": "解释核心概念", "mode": "detail"})
    assert chat.status_code == 201
    assert chat.json()["role"] == "assistant"
    exam = client.post("/api/workbench/exams", json={"subject_id": subject_id, "question_count": 12, "difficulty": "medium"})
    assert exam.status_code == 201
    assert exam.json()["questionCount"] == 12
