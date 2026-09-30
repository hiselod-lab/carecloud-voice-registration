import pytest
from fastapi.testclient import TestClient
from app.config import settings


@pytest.fixture
def payload():
    return {"first_name": "Avery", "last_name": "O'Neil", "date_of_birth": "03/14/1990", "sex": "Other", "phone_number": "(202) 555-0123", "address_line_1": "123 Demo Lane", "city": "Washington", "state": "DC", "zip_code": "20001", "email": "avery@example.com"}


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "test-api-token")
    monkeypatch.setattr(settings, "vapi_webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "demo_log_payloads", False)
    from app.main import create_app
    return create_app(f"sqlite:///{tmp_path / 'patients.db'}")


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as value:
        value.headers["Authorization"] = "Bearer test-api-token"
        yield value
