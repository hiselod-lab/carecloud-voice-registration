"""Synthetic, isolated tests for the authenticated Vapi review/save protocol."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.models import Patient
from app.voice import VoiceRegistration

VOICE_HEADERS = {"Authorization": "Bearer test-webhook-secret"}


def message(name, arguments, tool_id="tool-1", call_id="synthetic-call", text="My details", stamp=1):
    return {"message": {
        "type": "tool-calls", "call": {"id": call_id},
        "artifact": {"messages": [{"role": "user", "message": text, "time": stamp, "endTime": stamp}]},
        "toolCallList": [{"id": tool_id, "type": "function", "function": {"name": name, "arguments": arguments}}],
    }}


def invoke(client, name, arguments, tool_id="tool-1", call_id="synthetic-call", text="My details", stamp=1):
    response = client.post("/voice/webhook", json=message(name, arguments, tool_id, call_id, text, stamp), headers=VOICE_HEADERS)
    assert response.status_code == 200, response.text
    entry = response.json()["results"][0]
    assert entry["toolCallId"] == tool_id
    assert ("result" in entry) != ("error" in entry)
    kind = "result" if "result" in entry else "error"
    assert isinstance(entry[kind], str) and "\n" not in entry[kind]
    return kind, json.loads(entry[kind])


def patient_count(app):
    with app.state.session_factory() as db:
        return db.scalar(select(func.count()).select_from(Patient))


def review(client, payload, call_id="synthetic-call", stamp=1):
    kind, _ = invoke(client, "update_registration", {"fields": payload}, "update", call_id, stamp=stamp)
    assert kind == "result"
    kind, result = invoke(client, "review_registration", {}, "review", call_id, stamp=stamp)
    assert kind == "result"
    assert result["status"] == "awaiting_confirmation"
    assert result["live_transcript_available"] is True
    return result


@pytest.mark.parametrize("arguments", ["{broken", "null", "[]", "1", "true", '\"string\"',
                                       '{"n":NaN}', '{"n":Infinity}', [], None, True, 42])
def test_malformed_tool_arguments(client, app, arguments):
    kind, result = invoke(client, "update_registration", arguments)
    assert kind == "error" and result["code"] == "INVALID_ARGUMENTS"
    assert patient_count(app) == 0


@pytest.mark.parametrize("name", ["", "get_patient", "delete_patient", "__import__"])
def test_no_patient_lookup_or_unknown_tools(client, app, name):
    kind, result = invoke(client, name, {})
    assert kind == "error" and result["code"] == "UNKNOWN_TOOL"
    assert patient_count(app) == 0


@pytest.mark.parametrize("fields", [{"first_name": None}, {"date_of_birth": "02/29/2023"},
                                    {"phone_number": "123"}, {"unknown": "value"},
                                    {"sex": "Unspecified"}, {"state": "ZZ"}, {"preferred_language": None}])
def test_invalid_draft_fields_do_not_create_patient(client, app, fields):
    kind, _ = invoke(client, "update_registration", {"fields": fields})
    assert kind == "error" and patient_count(app) == 0


def test_webhook_auth_and_bad_envelopes(client, app):
    valid = message("update_registration", {"fields": {"first_name": "Avery"}})
    assert client.post("/voice/webhook", json=valid).status_code == 401
    response = client.post("/voice/webhook", content="{broken", headers=VOICE_HEADERS)
    assert response.status_code == 400 and response.json()["data"] is None
    for invalid in [None, {}, [], {"message": {}}, {"message": {"type": "tool-calls", "toolCallList": []}}]:
        assert client.post("/voice/webhook", json=invalid, headers=VOICE_HEADERS).status_code == 400
    assert patient_count(app) == 0


def test_batch_results_match_each_original_tool_id(client, app):
    body = message("update_registration", {"fields": {"first_name": "Avery"}}, "first")
    body["message"]["toolCallList"].extend([
        {"id": "second", "function": {"name": "update_registration", "arguments": "{"}},
        {"id": "third", "function": {"name": "review_registration", "arguments": {}}},
    ])
    response = client.post("/voice/webhook", json=body, headers=VOICE_HEADERS)
    assert response.status_code == 200
    results = response.json()["results"]
    assert [r["toolCallId"] for r in results] == ["first", "second", "third"]
    assert "result" in results[0] and "error" in results[1] and "error" in results[2]
    assert patient_count(app) == 0


def test_missing_call_id_yields_per_tool_error(client, app):
    body = message("update_registration", {"fields": {"first_name": "Avery"}})
    del body["message"]["call"]
    response = client.post("/voice/webhook", json=body, headers=VOICE_HEADERS)
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["toolCallId"] == "tool-1"
    assert json.loads(result["error"])["code"] == "CALL_ID_REQUIRED"
    assert patient_count(app) == 0


def test_readback_contains_all_required_and_optional_fields(client, app, payload):
    payload.update(insurance_provider="Demo Health", insurance_member_id="ABC123", address_line_2="Unit 2",
                   preferred_language="Spanish", emergency_contact_name="Demo Contact", emergency_contact_phone="2025550199")
    result = review(client, payload)
    for value in ["Avery", "O'Neil", "March 14, 1990", "Other", "2025550123", "123 Demo Lane",
                  "Washington", "DC", "20001", "avery@example.com", "Demo Health", "ABC123", "Unit 2",
                  "Spanish", "Demo Contact", "2025550199"]:
        assert value in result["readback"]
    assert patient_count(app) == 0


@pytest.mark.parametrize("confirmation", ["no", "not sure", "yes but my phone is wrong", "yes no",
                                          "save it after changing my name"])
def test_refusal_uncertainty_and_correction_are_not_consent(client, app, payload, confirmation):
    result = review(client, payload)
    kind, failure = invoke(client, "confirm_registration", {"review_token": result["review_token"], "confirmation": confirmation},
                           "confirm", text=confirmation, stamp=2)
    assert kind == "error" and failure["code"] == "EXPLICIT_CONFIRMATION_REQUIRED"
    assert patient_count(app) == 0


@pytest.mark.parametrize("evidence", ["stale", "missing", "mismatch", "filtered", "invalid_latest", "null_time"])
def test_confirmation_requires_current_unfiltered_actual_user_evidence(client, app, payload, evidence):
    result = review(client, payload)
    body = message("confirm_registration", {"review_token": result["review_token"], "confirmation": "yes"},
                   "confirm", text="yes", stamp=2)
    messages = body["message"]["artifact"]["messages"]
    if evidence == "stale":
        messages[0].update(time=1, endTime=1)
    elif evidence == "missing":
        del body["message"]["artifact"]
    elif evidence == "mismatch":
        messages[0]["message"] = "No, change my phone"
    elif evidence == "filtered":
        messages[0]["isFiltered"] = True
    elif evidence == "invalid_latest":
        messages.append({"role": "user", "message": None, "time": 3})
    else:
        messages[0].update(time=None, endTime=None)
    response = client.post("/voice/webhook", json=body, headers=VOICE_HEADERS)
    assert response.status_code == 200 and "error" in response.json()["results"][0]
    assert patient_count(app) == 0


def test_correction_invalidates_old_review_and_saves_corrected_record(client, app, payload):
    first = review(client, payload)
    assert invoke(client, "update_registration", {"fields": {"city": "Boston"}}, "correct")[0] == "result"
    args = {"review_token": first["review_token"], "confirmation": "yes"}
    assert invoke(client, "confirm_registration", args, "old-token", text="yes", stamp=2)[0] == "error"
    assert patient_count(app) == 0
    _, second = invoke(client, "review_registration", {}, "review-again", text="Change city", stamp=3)
    assert second["fields"]["city"] == "Boston" and second["review_token"] != first["review_token"]
    args["review_token"] = second["review_token"]
    kind, saved = invoke(client, "confirm_registration", args, "confirm", text="yes", stamp=4)
    assert kind == "result" and saved["status"] == "saved"
    with app.state.session_factory() as db:
        assert db.get(Patient, saved["patient_id"]).city == "Boston"


def test_expired_review_requires_fresh_readback(client, app, payload):
    result = review(client, payload)
    with app.state.session_factory() as db:
        registration = db.get(VoiceRegistration, "synthetic-call")
        registration.reviewed_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.commit()
    kind, failure = invoke(client, "confirm_registration", {"review_token": result["review_token"], "confirmation": "yes"},
                           "confirm", text="yes", stamp=2)
    assert kind == "error" and failure["code"] == "REVIEW_EXPIRED" and patient_count(app) == 0


def test_repeated_confirmation_does_not_duplicate_or_reset(client, app, payload):
    result = review(client, payload)
    args = {"review_token": result["review_token"], "confirmation": "yes"}
    _, first = invoke(client, "confirm_registration", args, "confirm", text="yes", stamp=2)
    for tool_id in ["confirm", "confirm-new-id"]:
        kind, repeated = invoke(client, "confirm_registration", args, tool_id, text="yes", stamp=2)
        assert kind == "result" and repeated["patient_id"] == first["patient_id"]
    assert patient_count(app) == 1
    assert invoke(client, "update_registration", {"reset": True}, "reset")[0] == "error"
    assert invoke(client, "update_registration", {"fields": {"city": "Boston"}}, "change")[0] == "error"
    assert patient_count(app) == 1


def test_tool_id_conflict_and_call_scope(client, app, payload):
    assert invoke(client, "update_registration", {"fields": {"first_name": "Avery"}}, "same")[0] == "result"
    kind, failure = invoke(client, "update_registration", {"fields": {"first_name": "Morgan"}}, "same")
    assert kind == "error" and failure["code"] == "TOOL_ID_CONFLICT"
    ids = []
    for call_id in ["first-call", "second-call"]:
        result = review(client, payload, call_id)
        kind, saved = invoke(client, "confirm_registration", {"review_token": result["review_token"], "confirmation": "yes"},
                             "same-confirm-id", call_id, text="yes", stamp=2)
        assert kind == "result"
        ids.append(saved["patient_id"])
    assert len(set(ids)) == 2 and patient_count(app) == 2


def test_reset_clears_draft_and_optional_fields_can_be_cleared(client, app, payload):
    review(client, payload)
    _, updated = invoke(client, "update_registration", {"fields": {"email": None}}, "clear-email")
    assert updated["fields"]["email"] is None
    _, reset = invoke(client, "update_registration", {"reset": True, "fields": {"first_name": "Morgan"}}, "reset")
    assert reset["fields"] == {"first_name": "Morgan"}
    assert "last_name" in reset["missing_fields"] and patient_count(app) == 0


def test_failed_commit_never_reports_saved_and_retry_is_safe(client, app, payload):
    result = review(client, payload)
    args = {"review_token": result["review_token"], "confirmation": "yes"}

    def unavailable_db():
        with app.state.session_factory() as db:
            def fail_commit():
                raise OperationalError("private database location", {}, Exception("sensitive detail"))
            db.commit = fail_commit
            yield db

    app.dependency_overrides[get_db] = unavailable_db
    kind, failure = invoke(client, "confirm_registration", args, "confirm", text="yes", stamp=2)
    assert kind == "error" and failure["code"] == "SAVE_UNAVAILABLE"
    assert "private" not in json.dumps(failure) and "sensitive" not in json.dumps(failure)
    app.dependency_overrides.clear()
    assert patient_count(app) == 0
    kind, saved = invoke(client, "confirm_registration", args, "confirm", text="yes", stamp=2)
    assert kind == "result" and saved["status"] == "saved" and patient_count(app) == 1


def test_saved_receipt_and_pending_review_survive_restart(tmp_path, payload, monkeypatch):
    from app.config import settings
    from app.main import create_app
    monkeypatch.setattr(settings, "vapi_webhook_secret", "test-webhook-secret")
    url = f"sqlite:///{tmp_path / 'voice-persistent.db'}"
    with TestClient(create_app(url)) as first:
        result = review(first, payload)
        args = {"review_token": result["review_token"], "confirmation": "yes"}
        _, saved = invoke(first, "confirm_registration", args, "confirm", text="yes", stamp=2)
        pending = review(first, payload, "second-call")
    restarted_app = create_app(url)
    with TestClient(restarted_app) as restarted:
        _, replay = invoke(restarted, "confirm_registration", args, "confirm", text="yes", stamp=2)
        assert replay["patient_id"] == saved["patient_id"] and patient_count(restarted_app) == 1
        kind, _ = invoke(restarted, "confirm_registration", {"review_token": pending["review_token"], "confirmation": "yes"},
                         "confirm", "second-call", text="yes", stamp=2)
        assert kind == "result" and patient_count(restarted_app) == 2


def test_concurrent_confirmation_creates_only_one_patient(client, app, payload):
    result = review(client, payload)
    args = {"review_token": result["review_token"], "confirmation": "yes"}

    def confirm(index):
        return invoke(client, "confirm_registration", args, f"parallel-{index}", text="yes", stamp=2)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(confirm, range(8)))
    successes = [result for kind, result in results if kind == "result"]
    assert successes and len({result["patient_id"] for result in successes}) == 1
    assert patient_count(app) == 1
    for index, (kind, _) in enumerate(results):
        if kind == "error":
            assert confirm(index)[0] == "result"
    assert patient_count(app) == 1


@pytest.mark.parametrize("source,expected", [
    (datetime(2026, 9, 30, 12, 30, tzinfo=timezone(timedelta(hours=-4))), "2026-09-30T16:30:00Z"),
    (datetime(2026, 9, 30, 16, 30), "2026-09-30T16:30:00Z"),
])
def test_saved_patient_timestamps_are_true_utc(payload, source, expected):
    from app.schemas import PatientCreate
    from app.services import serialize_patient
    patient = Patient(**PatientCreate.model_validate(payload).model_dump(), patient_id="synthetic-id",
                      created_at=source, updated_at=source, deleted_at=source)
    result = serialize_patient(patient)
    for field in ("created_at", "updated_at", "deleted_at"):
        assert result[field] == expected


def test_malformed_unicode_tool_argument_returns_matching_error(client, app):
    # JSON may escape a lone surrogate even though it is not valid UTF-8 text.
    body = message("update_registration", {"fields": {"city": "\ud800"}}, "bad-unicode")
    response = client.post("/voice/webhook", content=json.dumps(body), headers={**VOICE_HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["toolCallId"] == "bad-unicode"
    assert json.loads(item["error"])["code"] == "INVALID_ARGUMENTS"
    assert patient_count(app) == 0


def test_malformed_unicode_transcript_fails_closed(client, app, payload):
    result = review(client, payload)
    body = message("confirm_registration", {"review_token": result["review_token"], "confirmation": "yes"},
                   "bad-transcript", text="\ud800", stamp=2)
    response = client.post("/voice/webhook", content=json.dumps(body), headers={**VOICE_HEADERS, "Content-Type": "application/json"})
    assert response.status_code == 200
    item = response.json()["results"][0]
    assert item["toolCallId"] == "bad-transcript"
    assert json.loads(item["error"])["code"] == "CONFIRMATION_TRANSCRIPT_REQUIRED"
    assert patient_count(app) == 0


def test_malformed_unicode_rest_value_is_validation_error(client, app, payload):
    payload["city"] = "\ud800"
    response = client.post("/patients", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "validation_error"
    assert patient_count(app) == 0
