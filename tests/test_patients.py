from datetime import date, timedelta
from uuid import UUID, uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, IntegrityError
from app.config import settings
from app.database import get_db
from app.models import Patient


def test_create_get_list_update_delete(client, payload, app):
    response = client.post("/patients", json=payload)
    assert response.status_code == 201
    row = response.json()["data"]
    UUID(row["patient_id"])
    assert row["phone_number"] == "2025550123"
    assert row["date_of_birth"] == "03/14/1990"
    assert row["preferred_language"] == "English"
    assert row["created_at"].endswith("Z")
    path = f"/patients/{row['patient_id']}"
    assert client.get(path).json()["data"] == row
    listing = client.get("/patients").json()
    assert listing["meta"]["total"] == 1
    assert listing["data"][0]["patient_id"] == row["patient_id"]
    result = client.put(path, json={"first_name": "Morgan", "email": None}).json()["data"]
    assert result["first_name"] == "Morgan"
    assert result["last_name"] == payload["last_name"]
    assert result["email"] is None
    assert result["updated_at"] >= row["updated_at"]
    assert client.delete(path).status_code == 200
    assert client.get(path).status_code == 404
    assert client.get("/patients").json()["meta"]["total"] == 0
    assert client.put(path, json={"city": "Boston"}).status_code == 404
    assert client.delete(path).status_code == 404
    with app.state.session_factory() as db:
        assert db.get(Patient, row["patient_id"]).deleted_at is not None


@pytest.mark.parametrize("field,value", [
    ("first_name", ""), ("first_name", "A" * 51), ("first_name", "Abc1"), ("first_name", "---"),
    ("last_name", "Name Here"), ("last_name", "A_"), ("date_of_birth", "02/29/2023"),
    ("date_of_birth", "13/01/2000"), ("date_of_birth", "1/2/1990"), ("date_of_birth", (date.today()+timedelta(days=1)).strftime("%m/%d/%Y")),
    ("sex", "Unknown"), ("phone_number", "123"), ("phone_number", "202555012a"),
    ("address_line_1", " "), ("city", ""), ("city", "A" * 101), ("state", "ZZ"), ("state", "California"),
    ("zip_code", "1234"), ("zip_code", "123456"), ("zip_code", "ABCDE"), ("zip_code", "12345-678"),
    ("email", "invalid"), ("insurance_member_id", "AB-123"), ("insurance_member_id", "å123"),
    ("emergency_contact_phone", "123"), ("emergency_contact_name", "Joe2"), ("preferred_language", ""),
])
def test_validation(client, payload, field, value):
    payload[field] = value
    response = client.post("/patients", json=payload)
    assert response.status_code == 422, response.text
    assert response.json()["data"] is None
    assert response.json()["error"]["code"] == "validation_error"
    assert client.get("/patients").json()["meta"]["total"] == 0


@pytest.mark.parametrize("field", ["first_name", "last_name", "date_of_birth", "sex", "phone_number", "address_line_1", "city", "state", "zip_code"])
def test_required_fields(client, payload, field):
    del payload[field]
    assert client.post("/patients", json=payload).status_code == 422


def test_optional_normalization_and_valid_boundaries(client, payload):
    payload.update(first_name="Anne-Marie", last_name="D'Arcy", date_of_birth="2000-02-29", state="ny", zip_code="10001-1234", phone_number="+1 212-555-0100", emergency_contact_name="Demo Contact", emergency_contact_phone="(212) 555-0101", insurance_member_id="ABC123", email="", address_line_2="", insurance_provider="Demo Health")
    r = client.post("/patients", json=payload)
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["state"] == "NY"
    assert data["email"] is None
    assert data["address_line_2"] is None
    assert data["emergency_contact_phone"] == "2125550101"
    assert data["date_of_birth"] == "02/29/2000"


def test_filtering_and_pagination(client, payload):
    client.post("/patients", json=payload)
    second = dict(payload, last_name="Smith", phone_number="2025550199", date_of_birth="12/31/1985")
    client.post("/patients", json=second)
    for query in ({"last_name": "o'neil"}, {"phone_number": "+1 202-555-0123"}, {"date_of_birth": "1990-03-14"}):
        result = client.get("/patients", params=query).json()
        assert result["meta"]["total"] == 1
        assert result["data"][0]["last_name"] == "O'Neil"
    assert client.get("/patients", params={"last_name": "%' OR 1=1 --"}).json()["data"] == []
    result = client.get("/patients?limit=1&offset=1").json()
    assert len(result["data"]) == 1
    assert result["meta"]["total"] == 2
    assert client.get("/patients?date_of_birth=bad").status_code == 422
    assert client.get("/patients?phone_number=bad").status_code == 422
    assert client.get("/patients?limit=1000").status_code == 422


def test_errors_and_auth(client, payload):
    assert client.post("/patients", content="{broken", headers={"Content-Type": "application/json"}).status_code == 400
    assert client.post("/patients", json=dict(payload, unknown="field")).status_code == 422
    assert client.get("/patients/not-a-uuid").status_code == 422
    assert client.get(f"/patients/{uuid4()}").status_code == 404
    assert client.get("/not-real").json()["error"]["code"] == "not_found"
    assert client.get("/patients", headers={"Authorization": "Bearer incorrect"}).status_code == 401
    assert client.get("/patients", headers={"Authorization": ""}).status_code == 401
    assert client.get("/health").json()["status"] == "ok"
    row = client.post("/patients", json=payload).json()["data"]
    url = f"/patients/{row['patient_id']}"
    assert client.put(url, json={}).status_code == 400
    assert client.put(url, json={"first_name": None}).status_code == 422
    assert client.put(url, json={"phone_number": "12"}).status_code == 422
    assert client.get(url).json()["data"]["phone_number"] == "2025550123"


def test_auth_fails_closed(client, monkeypatch):
    monkeypatch.setattr(settings, "api_bearer_token", "")
    assert client.get("/patients").status_code == 503


def test_database_failure(client, app, payload):
    class BrokenSession:
        def add(self, value):
            raise OperationalError("secret db location", {}, Exception("private"))
        def rollback(self):
            pass
    app.dependency_overrides[get_db] = lambda: BrokenSession()
    r = client.post("/patients", json=payload)
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "database_error"
    assert "secret" not in r.text and "private" not in r.text


def test_restart_persistence(tmp_path, payload, monkeypatch):
    from app.main import create_app
    monkeypatch.setattr(settings, "api_bearer_token", "test")
    url = f"sqlite:///{tmp_path / 'persistent.db'}"
    with TestClient(create_app(url), headers={"Authorization": "Bearer test"}) as first:
        patient_id = first.post("/patients", json=payload).json()["data"]["patient_id"]
    with TestClient(create_app(url), headers={"Authorization": "Bearer test"}) as restarted:
        assert restarted.get(f"/patients/{patient_id}").status_code == 200
        assert restarted.get("/patients").json()["meta"]["total"] == 1


def test_database_constraints(client, app, payload):
    patient_id = client.post("/patients", json=payload).json()["data"]["patient_id"]
    with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE patients SET sex='Invalid' WHERE patient_id=:id"), {"id": patient_id})
            db.commit()
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(text("UPDATE patients SET phone_number='123' WHERE patient_id=:id"), {"id": patient_id})
            db.commit()


def test_response_security_headers(client):
    r = client.get("/patients")
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
