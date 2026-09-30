"""Vapi Function tools with a durable, fail-closed review/consent protocol.

No tool can search for patients. Drafts are scoped to an authenticated provider
call ID, and a patient and its saved-session marker commit in one transaction.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.config import settings
from app.database import Base, get_db
from app.errors import ApiError
from app.schemas import PatientCreate, PatientUpdate
from app.services import create_patient, serialize_patient

logger = logging.getLogger("carecloud.voice")

router = APIRouter(prefix="/voice", tags=["Voice registration"])
REVIEW_TTL_SECONDS = 15 * 60
MAX_BODY_BYTES = 1_000_000
MAX_TOOLS_PER_REQUEST = 20
REQUIRED_FIELDS = (
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
)
FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name",
    "date_of_birth": "Date of birth", "sex": "Sex", "phone_number": "Phone number",
    "email": "Email", "address_line_1": "Address line one", "address_line_2": "Address line two",
    "city": "City", "state": "State", "zip_code": "ZIP code",
    "insurance_provider": "Insurance provider", "insurance_member_id": "Insurance member ID",
    "preferred_language": "Preferred language", "emergency_contact_name": "Emergency contact name",
    "emergency_contact_phone": "Emergency contact phone",
}
OPTIONAL_FIELDS = tuple(name for name in FIELD_LABELS if name not in REQUIRED_FIELDS)


class VoiceRegistration(Base):
    __tablename__ = "voice_registrations"

    call_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    draft: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="collecting", nullable=False)
    review_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reviewed_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_user_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_user_time: Mapped[float | None] = mapped_column(JSON, nullable=True)
    saved_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class VoiceToolReceipt(Base):
    __tablename__ = "voice_tool_receipts"
    __table_args__ = (UniqueConstraint("call_id", "tool_call_id", name="uq_voice_tool_receipt"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    call_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    tool_call_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class UpdateArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Any] = Field(default_factory=dict)
    reset: StrictBool = False


class ReviewArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    review_token: str = Field(min_length=20, max_length=64)
    confirmation: str = Field(min_length=1, max_length=300)


@dataclass(frozen=True)
class UserEvidence:
    text: str
    fingerprint: str
    time: float


@dataclass
class ToolFailure(Exception):
    code: str
    message: str
    details: Any = None


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _failure(code: str, message: str, details: Any = None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": _compact(error)}


def _validation_details(exc: ValidationError) -> list[dict]:
    # Deliberately omit Pydantic's input and context, which may contain PHI.
    return [{"field": ".".join(map(str, e["loc"])), "message": e["msg"], "type": e["type"]}
            for e in exc.errors(include_input=False, include_context=False, include_url=False)]


def _normalize_confirmation(value: str) -> str:
    value = value.casefold().replace("’", "'")
    return " ".join(re.sub(r"[^\w\s']", " ", value, flags=re.UNICODE).split())


AFFIRMATIVE_CONFIRMATIONS = frozenset({
    "yes", "yes please", "yes that's correct", "yes that is correct", "that's correct",
    "that is correct", "correct", "please save it", "save it", "yes save it",
    "yes please save it", "yes please save", "yes save my registration", "yes please save my registration",
    "i confirm", "i confirm everything is correct", "everything is correct",
    "yes everything is correct", "confirm and save", "yes confirm and save",
    "go ahead and save", "yes go ahead and save", "yes it is correct", "yes correct",
})


def _latest_user_evidence(message: dict) -> UserEvidence | None:
    artifact = message.get("artifact")
    if not isinstance(artifact, dict) or not isinstance(artifact.get("messages"), list):
        return None
    # Inspect the last actual user entry, never skip a filtered/invalid one and
    # accidentally use an older affirmative utterance.
    for item in reversed(artifact["messages"]):
        if not isinstance(item, dict) or item.get("role") != "user":
            continue
        if item.get("isFiltered") or not isinstance(item.get("message"), str):
            return None
        stamp = item.get("endTime", item.get("time"))
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return None
        # Reject NaN/infinities and oversized transcript entries.
        if not (-1e16 < stamp < 1e16) or len(item["message"]) > 10_000:
            return None
        try:
            fingerprint = hashlib.sha256(_compact({"text": item["message"], "time": stamp}).encode()).hexdigest()
        except (ValueError, TypeError):
            return None
        return UserEvidence(item["message"], fingerprint, float(stamp))
    return None


def _require_webhook_auth(request: Request) -> None:
    expected = settings.vapi_webhook_secret
    if hasattr(expected, "get_secret_value"):
        expected = expected.get_secret_value()
    if not expected:
        raise ApiError(503, "VOICE_NOT_CONFIGURED", "Voice registration is not configured.")
    supplied = request.headers.get("x-vapi-secret", "")
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied.encode(), str(expected).encode()):
        raise ApiError(401, "UNAUTHORIZED", "Invalid voice webhook credentials.")


def _load_registration(db: Session, call_id: str) -> VoiceRegistration:
    registration = db.scalar(select(VoiceRegistration).where(VoiceRegistration.call_id == call_id).with_for_update())
    if registration is None:
        registration = VoiceRegistration(call_id=call_id, draft={}, version=0, status="collecting")
        db.add(registration)
        db.flush()
    return registration


def _ensure_editable(registration: VoiceRegistration) -> None:
    if registration.status == "saved":
        raise ToolFailure("ALREADY_SAVED", "This call already saved a registration. Do not create another patient. Start a new call for a different patient.")


def _missing_fields(draft: dict) -> list[str]:
    return [name for name in REQUIRED_FIELDS if draft.get(name) in (None, "")]


def _patient_payload(draft: dict) -> dict:
    return PatientCreate.model_validate(draft).model_dump(mode="json")


def _readback(payload: dict) -> str:
    values = []
    for name, label in FIELD_LABELS.items():
        value = payload.get(name)
        if name == "date_of_birth" and isinstance(value, str):
            try:
                value = datetime.strptime(value, "%Y-%m-%d").strftime("%B %d, %Y")
            except ValueError:
                pass
        if value is None or value == "":
            value = "not provided"
        values.append(f"{label}: {value}.")
    return "Please check every detail. " + " ".join(values) + " Is everything correct, and may I save your registration? Say yes to save, or tell me what to change."


def _update_registration(db: Session, registration: VoiceRegistration, arguments: dict) -> dict:
    args = UpdateArguments.model_validate(arguments)
    _ensure_editable(registration)
    if not args.fields and not args.reset:
        raise ToolFailure("EMPTY_UPDATE", "Provide fields to update, or set reset to true to start over.")
    unknown = sorted(set(args.fields) - set(FIELD_LABELS))
    if unknown:
        raise ToolFailure("INVALID_FIELDS", "Use only supported patient registration fields.", {"fields": unknown})
    null_required = [name for name in REQUIRED_FIELDS if name in args.fields and args.fields[name] is None]
    if null_required:
        raise ToolFailure("INVALID_FIELDS", "Required fields cannot be cleared to null; use reset to start over.", {"fields": null_required})
    patch = PatientUpdate.model_validate(args.fields).model_dump(exclude_unset=True, mode="json")
    draft = {} if args.reset else dict(registration.draft)
    draft.update(patch)
    old_version = registration.version
    changed = db.execute(update(VoiceRegistration).where(
        VoiceRegistration.call_id == registration.call_id,
        VoiceRegistration.version == old_version,
        VoiceRegistration.status != "saved",
    ).values(
        draft=draft, version=old_version + 1, status="collecting", review_token=None,
        reviewed_version=None, reviewed_payload=None, reviewed_at=None,
        review_user_fingerprint=None, review_user_time=None, updated_at=datetime.now(timezone.utc),
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ToolFailure("DRAFT_CHANGED", "Another request changed this draft. Retry the update, then review all details again.")
    missing = _missing_fields(draft)
    return {"status": "collecting", "draft_version": old_version + 1, "fields": draft,
            "missing_fields": missing, "optional_fields": list(OPTIONAL_FIELDS),
            "next_step": "Ask naturally for missing required fields; offer optional fields before review." if missing else "Offer any remaining optional fields, then call review_registration. Nothing has been saved."}


def _review_registration(db: Session, registration: VoiceRegistration, arguments: dict, evidence: UserEvidence | None) -> dict:
    ReviewArguments.model_validate(arguments)
    _ensure_editable(registration)
    payload = _patient_payload(registration.draft)
    token = secrets.token_urlsafe(32)
    changed = db.execute(update(VoiceRegistration).where(
        VoiceRegistration.call_id == registration.call_id,
        VoiceRegistration.version == registration.version,
        VoiceRegistration.status != "saved",
    ).values(
        status="reviewed", review_token=token, reviewed_version=registration.version,
        reviewed_payload=payload, reviewed_at=datetime.now(timezone.utc),
        review_user_fingerprint=evidence.fingerprint if evidence else None,
        review_user_time=evidence.time if evidence else None,
        updated_at=datetime.now(timezone.utc),
    ).execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        raise ToolFailure("DRAFT_CHANGED", "The draft changed. Review the latest details before asking for confirmation.")
    return {"status": "awaiting_confirmation", "draft_version": registration.version,
            "review_token": token, "expires_in_seconds": REVIEW_TTL_SECONDS,
            "fields": payload, "readback": _readback(payload),
            "live_transcript_available": evidence is not None,
            "next_step": "Read every word of readback aloud. Wait for a new, explicit yes. For any correction, update the draft and review again. Never save merely because the fields are complete."}


def _confirm_registration(db: Session, registration: VoiceRegistration, arguments: dict, evidence: UserEvidence | None) -> dict:
    args = ConfirmArguments.model_validate(arguments)
    if not registration.review_token or not hmac.compare_digest(args.review_token, registration.review_token):
        raise ToolFailure("REVIEW_REQUIRED", "A current full review is required before saving. Call review_registration and read every field aloud.")
    if registration.status == "saved":
        return {**registration.saved_result, "already_saved": True}
    if registration.status != "reviewed" or registration.reviewed_version != registration.version or not registration.reviewed_payload:
        raise ToolFailure("REVIEW_REQUIRED", "The reviewed draft is no longer current. Review all details again before saving.")
    reviewed_at = registration.reviewed_at
    if reviewed_at is None:
        raise ToolFailure("REVIEW_REQUIRED", "Review all details before saving.")
    if reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > reviewed_at + timedelta(seconds=REVIEW_TTL_SECONDS):
        raise ToolFailure("REVIEW_EXPIRED", "The review expired. Read all details again and obtain a fresh confirmation.")
    normalized = _normalize_confirmation(args.confirmation)
    if normalized not in AFFIRMATIVE_CONFIRMATIONS:
        raise ToolFailure("EXPLICIT_CONFIRMATION_REQUIRED", "The patient has not clearly approved this exact registration. Ask whether everything is correct and whether to save; do not save a correction, refusal, or uncertain answer.")
    if evidence is None or not registration.review_user_fingerprint or registration.review_user_time is None:
        raise ToolFailure("CONFIRMATION_TRANSCRIPT_REQUIRED", "A live user transcript is required to verify confirmation. Read the review again, wait for the patient's yes, and retry. If this repeats, ask staff for help; nothing was saved.")
    if evidence.fingerprint == registration.review_user_fingerprint or evidence.time <= registration.review_user_time:
        raise ToolFailure("NEW_CONFIRMATION_REQUIRED", "Wait for a new patient answer after the full review before saving.")
    if _normalize_confirmation(evidence.text) != normalized or _normalize_confirmation(evidence.text) not in AFFIRMATIVE_CONFIRMATIONS:
        raise ToolFailure("CONFIRMATION_MISMATCH", "The latest patient answer does not explicitly approve saving. Process any correction, review all fields again, and ask for confirmation.")
    claimed = db.execute(update(VoiceRegistration).where(
        VoiceRegistration.call_id == registration.call_id,
        VoiceRegistration.status == "reviewed",
        VoiceRegistration.version == registration.reviewed_version,
        VoiceRegistration.review_token == args.review_token,
    ).values(status="saving").execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        # No partial patient insertion has occurred. A concurrent caller may have
        # completed this same nonce; retry returns its durable saved receipt.
        raise ToolFailure("DRAFT_CHANGED", "The registration changed during saving. Retry this same confirmation; do not create a new registration.")
    patient = create_patient(db, PatientCreate.model_validate(registration.reviewed_payload), commit=False)
    serialized = serialize_patient(patient)
    result = {"status": "saved", "patient_id": serialized["patient_id"], "already_saved": False,
              "message": "Registration saved successfully. Thank you. Have a good day."}
    db.execute(update(VoiceRegistration).where(VoiceRegistration.call_id == registration.call_id).values(
        status="saved", saved_result=result, saved_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
    ).execution_options(synchronize_session=False))
    # execute_tool commits this patient, state marker, and receipt together. It
    # does not expose this success result until that commit has succeeded.
    return result


def execute_tool(db: Session, call_id: str, tool_call_id: str, name: str, arguments: dict,
                 evidence: UserEvidence | None = None) -> dict:
    """Run a tool atomically. Returned dict is one Vapi result/error fragment."""
    try:
        fingerprint = hashlib.sha256(_compact({"name": name, "arguments": arguments}).encode()).hexdigest()
    except (ValueError, TypeError):
        return _failure("INVALID_ARGUMENTS", "Tool arguments must contain valid Unicode text and JSON values.")
    try:
        db.expire_all()
        receipt = db.scalar(select(VoiceToolReceipt).where(
            VoiceToolReceipt.call_id == call_id, VoiceToolReceipt.tool_call_id == tool_call_id))
        if receipt:
            if receipt.request_hash != fingerprint:
                return _failure("TOOL_ID_CONFLICT", "This tool call ID was already used for different arguments. Use a new tool call ID.")
            return receipt.response
        if name not in {"update_registration", "review_registration", "confirm_registration"}:
            raise ToolFailure("UNKNOWN_TOOL", "This tool is not supported. Use update_registration, review_registration, or confirm_registration.")
        registration = _load_registration(db, call_id)
        if name == "update_registration":
            result = _update_registration(db, registration, arguments)
        elif name == "review_registration":
            result = _review_registration(db, registration, arguments, evidence)
        else:
            result = _confirm_registration(db, registration, arguments, evidence)
        response = {"result": _compact(result)}
        db.add(VoiceToolReceipt(call_id=call_id, tool_call_id=tool_call_id, request_hash=fingerprint, response=response))
        db.commit()
        if name == "confirm_registration" and not result.get("already_saved") and settings.demo_log_payloads:
            logger.warning("SYNTHETIC DEMO ONLY committed_voice_patient=%s", _compact({"patient_id": result["patient_id"], **registration.reviewed_payload}))
        return response
    except ToolFailure as exc:
        db.rollback()
        return _failure(exc.code, exc.message, exc.details)
    except ValidationError as exc:
        db.rollback()
        return _failure("VALIDATION_ERROR", "Some registration details need correction. Ask for the listed fields and try again.", _validation_details(exc))
    except ApiError as exc:
        db.rollback()
        return _failure(getattr(exc, "code", "REGISTRATION_ERROR"), getattr(exc, "message", "Registration could not be saved. Check the details and try again."))
    except IntegrityError:
        db.rollback()
        # Another delivery may have committed the exact request while we waited.
        receipt = db.scalar(select(VoiceToolReceipt).where(
            VoiceToolReceipt.call_id == call_id, VoiceToolReceipt.tool_call_id == tool_call_id))
        if receipt and receipt.request_hash == fingerprint:
            return receipt.response
        return _failure("RETRY_REQUIRED", "The registration request overlapped another request. Retry the same tool call. Do not claim success yet.")
    except Exception:
        # Provider-facing responses and app logs never include raw database
        # exceptions, patient data, transcripts, credentials, or stack traces.
        db.rollback()
        return _failure("SAVE_UNAVAILABLE", "Registration could not be completed right now. Nothing is confirmed saved. Retry the same request; if it fails again, ask staff for help.")


@router.post("/webhook")
async def voice_webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    _require_webhook_auth(request)
    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise ApiError(413, "PAYLOAD_TOO_LARGE", "Voice webhook payload is too large.")
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "INVALID_JSON", "The webhook body must be valid JSON.")
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ApiError(400, "INVALID_WEBHOOK", "The webhook must include a message with a type.")
    if message["type"] != "tool-calls":
        return {"ok": True}
    tool_calls = message.get("toolCallList")
    if not isinstance(tool_calls, list) or not 1 <= len(tool_calls) <= MAX_TOOLS_PER_REQUEST:
        raise ApiError(400, "INVALID_TOOL_CALLS", "Provide one to twenty tool calls.")
    for item in tool_calls:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not 1 <= len(item["id"]) <= 200:
            raise ApiError(400, "INVALID_TOOL_CALL_ID", "Each tool call must include a valid ID.")
    call = message.get("call")
    call_id = call.get("id") if isinstance(call, dict) else None
    valid_call_id = isinstance(call_id, str) and 1 <= len(call_id.strip()) <= 200 and call_id == call_id.strip()
    evidence = _latest_user_evidence(message)
    results = []
    for item in tool_calls:
        if not valid_call_id:
            response = _failure("CALL_ID_REQUIRED", "A provider call ID is required. No registration was saved.")
        else:
            function = item.get("function")
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                response = _failure("INVALID_TOOL_CALL", "Each tool call must include a function name and arguments.")
            else:
                arguments = function.get("arguments", {})
                try:
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("Expected arguments object")
                    # Reject JSON's nonstandard NaN/Infinity before hashing or DB serialization.
                    _compact(arguments).encode("utf-8")
                except (ValueError, TypeError):
                    response = _failure("INVALID_ARGUMENTS", "Tool arguments must be a valid JSON object.")
                else:
                    response = execute_tool(db, call_id, item["id"], function["name"], arguments, evidence)
        results.append({"toolCallId": item["id"], **response})
    return {"results": results}
