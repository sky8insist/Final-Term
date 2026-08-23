import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user
from app.main import app
from app.models.user import CurrentUser
from app.services import rag_service

client = TestClient(app)
USER_ID = "00000000-0000-0000-0000-000000000001"
SUBJECT_ID = "00000000-0000-0000-0000-000000000010"


@pytest.fixture(autouse=True)
def clear_dependency_overrides():
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


def use_test_user() -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=USER_ID,
        email="student@example.com",
        role="authenticated",
    )


def test_chat_ask_requires_login():
    response = client.post(
        "/chat/ask",
        json={"subjectId": SUBJECT_ID, "question": "What should I review?"},
    )

    assert response.status_code == 401


def test_chat_ask_rejects_empty_question():
    use_test_user()
    response = client.post(
        "/chat/ask",
        json={"subjectId": SUBJECT_ID, "question": "   "},
    )

    assert response.status_code == 422


def test_chat_ask_returns_answer_and_citations(monkeypatch):
    use_test_user()

    async def fake_answer_with_rag(**kwargs):
        assert kwargs["user_id"] == USER_ID
        assert kwargs["subject_id"] == SUBJECT_ID
        assert "考试作答标准" in kwargs["teaching_instruction"]
        return {
            "answer": "这是中文答案。",
            "messageId": "msg-1",
            "citations": [
                {
                    "id": "mat-1:0",
                    "materialId": "mat-1",
                    "sourceName": "notes.txt #0",
                    "text": "retrieved text",
                    "score": None,
                }
            ],
        }

    monkeypatch.setattr(rag_service, "answer_with_rag", fake_answer_with_rag)

    response = client.post(
        "/chat/ask",
        json={"subjectId": SUBJECT_ID, "question": "What should I review?", "mode": "exam"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "这是中文答案。"
    assert response.json()["messageId"] == "msg-1"
    assert response.json()["citations"][0]["materialId"] == "mat-1"
