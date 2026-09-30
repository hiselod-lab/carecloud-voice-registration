import json
import logging
from datetime import timezone
from sqlalchemy.orm import Session
from app.config import settings
from app.errors import ApiError
from app.models import Patient
from app.schemas import PatientCreate

logger = logging.getLogger("carecloud")
PATIENT_FIELDS = tuple(PatientCreate.model_fields)


def serialize_patient(patient: Patient) -> dict:
    result = {key: getattr(patient, key) for key in PATIENT_FIELDS}
    result["date_of_birth"] = patient.date_of_birth.strftime("%m/%d/%Y")
    result["patient_id"] = patient.patient_id
    for field in ("created_at", "updated_at", "deleted_at"):
        timestamp = getattr(patient, field)
        result[field] = (timestamp.astimezone(timezone.utc) if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)).isoformat().replace("+00:00", "Z") if timestamp else None
    return result


def create_patient(db: Session, payload: PatientCreate, *, commit: bool = True) -> Patient:
    patient = Patient(**payload.model_dump())
    db.add(patient)
    db.flush()
    if commit:
        db.commit()
        if settings.demo_log_payloads:
            logger.warning("SYNTHETIC DEMO ONLY committed_patient=%s", json.dumps(serialize_patient(patient), ensure_ascii=False))
    return patient


def get_patient(db: Session, patient_id: str) -> Patient:
    patient = db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise ApiError(404, "patient_not_found", "Patient not found")
    return patient
