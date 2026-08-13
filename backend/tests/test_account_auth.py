from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.supabase_client import get_supabase_client
from app.main import app


class FakeTable:
    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=[self.payload])


class FakeAdmin:
    def __init__(self):
        self.payload = None

    def create_user(self, payload):
        self.payload = payload
        return SimpleNamespace(user=SimpleNamespace(id="00000000-0000-0000-0000-000000000123"))


class FakeClient:
    def __init__(self):
        self.auth = SimpleNamespace(admin=FakeAdmin())
        self.profile = FakeTable()

    def table(self, name):
        assert name == "profiles"
        return self.profile


def test_account_registration_normalizes_username_and_confirms_internal_identity():
    fake = FakeClient()
    app.dependency_overrides[get_supabase_client] = lambda: fake
    # The route imports the provider directly, so patch its module-level binding.
    import app.api.auth as auth_api
    original = auth_api.get_supabase_client
    auth_api.get_supabase_client = lambda: fake
    try:
        response = TestClient(app).post("/api/v1/auth/account/register", json={"username": "Study_User", "password": "password123"})
    finally:
        auth_api.get_supabase_client = original
        app.dependency_overrides.clear()
    assert response.status_code == 201
    assert response.json()["loginIdentifier"] == "study_user@account.examai.local"
    assert fake.auth.admin.payload["email_confirm"] is True
    assert fake.profile.payload["username"] == "study_user"


def test_account_registration_rejects_invalid_username():
    response = TestClient(app).post("/api/v1/auth/account/register", json={"username": "12", "password": "password123"})
    assert response.status_code == 422
