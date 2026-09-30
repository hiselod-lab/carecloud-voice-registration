"""Same-origin dashboard, authenticated patient REST API, and Vapi webhook."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException
from app.config import settings
from app.database import Base, get_db, make_engine, make_session_factory
from app.errors import ApiError, error_body
from app.models import Patient, utcnow
from app.schemas import PatientCreate, PatientUpdate, normalize_phone, parse_dob
from app.security import require_api_auth
from app.services import create_patient, get_patient, serialize_patient

logger = logging.getLogger("carecloud")
STATIC = Path(__file__).parent / "static"


def validation_details(errors):
    return [{"field": ".".join(str(v) for v in e["loc"] if v not in ("body", "query", "path")), "message": e["msg"]} for e in errors]


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url or settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(engine)
        yield
        engine.dispose()

    app = FastAPI(title="CareCloud Patient Registration", version="1.0.0", lifespan=lifespan,
                  description="Synthetic-data assessment demo. Every patient endpoint requires bearer authentication.")
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)

    @app.exception_handler(ApiError)
    async def application_error(request, exc):
        headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(request, exc):
        is_json = any(error["type"] == "json_invalid" for error in exc.errors())
        return JSONResponse(error_body("invalid_json" if is_json else "validation_error", "Malformed JSON body" if is_json else "Please correct the highlighted fields", validation_details(exc.errors())), status_code=400 if is_json else 422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(error_body("not_found" if exc.status_code == 404 else "http_error", str(exc.detail)), status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(error_body("database_error", "Unable to complete the request. Please try again."), status_code=500)

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        logger.error("Unexpected request failure: %s", type(exc).__name__)
        return JSONResponse(error_body("internal_error", "Unable to complete the request. Please try again."), status_code=500)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=(self)"
        if request.url.path.startswith(("/patients", "/voice")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health", tags=["system"])
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/config", tags=["system"])
    def config():
        return {"data": {"auth_required": True, "voice_enabled": bool(settings.vapi_public_key and settings.vapi_assistant_id and settings.vapi_webhook_secret), "vapi_public_key": settings.vapi_public_key or None, "vapi_assistant_id": settings.vapi_assistant_id or None}, "error": None}

    @app.get("/patients", dependencies=[Depends(require_api_auth)], tags=["patients"])
    def list_patients(last_name: str | None = Query(default=None, max_length=50), date_of_birth: str | None = None,
                      phone_number: str | None = None, limit: int = Query(default=50, ge=1, le=100),
                      offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
        criteria = [Patient.deleted_at.is_(None)]
        if last_name:
            # Exact case-insensitive match; do not interpret caller input as a LIKE pattern.
            criteria.append(func.lower(Patient.last_name) == last_name.strip().lower())
        if date_of_birth:
            try:
                criteria.append(Patient.date_of_birth == parse_dob(date_of_birth))
            except ValueError as exc:
                raise ApiError(422, "validation_error", "Invalid date_of_birth filter", [{"field": "date_of_birth", "message": str(exc)}]) from None
        if phone_number:
            try:
                criteria.append(Patient.phone_number == normalize_phone(phone_number))
            except ValueError as exc:
                raise ApiError(422, "validation_error", "Invalid phone_number filter", [{"field": "phone_number", "message": str(exc)}]) from None
        total = db.scalar(select(func.count()).select_from(Patient).where(*criteria))
        patients = db.scalars(select(Patient).where(*criteria).order_by(Patient.created_at.desc(), Patient.patient_id).offset(offset).limit(limit)).all()
        return {"data": [serialize_patient(p) for p in patients], "error": None, "meta": {"total": total, "limit": limit, "offset": offset}}

    @app.get("/patients/{patient_id}", dependencies=[Depends(require_api_auth)], tags=["patients"])
    def read_patient(patient_id: UUID, db: Session = Depends(get_db)):
        return {"data": serialize_patient(get_patient(db, str(patient_id))), "error": None}

    @app.post("/patients", status_code=201, dependencies=[Depends(require_api_auth)], tags=["patients"])
    def add_patient(payload: PatientCreate, db: Session = Depends(get_db)):
        patient = create_patient(db, payload)
        return {"data": serialize_patient(patient), "error": None}

    @app.put("/patients/{patient_id}", dependencies=[Depends(require_api_auth)], tags=["patients"])
    def update_patient(patient_id: UUID, payload: PatientUpdate, db: Session = Depends(get_db)):
        patient = get_patient(db, str(patient_id))
        patch = payload.model_dump(exclude_unset=True)
        if not patch:
            raise ApiError(400, "empty_update", "Provide at least one field to update")
        full_data = {name: getattr(patient, name) for name in PatientCreate.model_fields}
        full_data.update(patch)
        try:
            validated = PatientCreate.model_validate(full_data)
        except ValidationError as exc:
            raise ApiError(422, "validation_error", "Invalid patient update", validation_details(exc.errors())) from None
        for name, value in validated.model_dump().items():
            setattr(patient, name, value)
        patient.updated_at = utcnow()
        db.commit()
        return {"data": serialize_patient(patient), "error": None}

    @app.delete("/patients/{patient_id}", dependencies=[Depends(require_api_auth)], tags=["patients"])
    def delete_patient(patient_id: UUID, db: Session = Depends(get_db)):
        patient = get_patient(db, str(patient_id))
        patient.deleted_at = utcnow()
        patient.updated_at = patient.deleted_at
        db.commit()
        return {"data": {"patient_id": patient.patient_id, "deleted": True}, "error": None}

    # Import before startup so voice tables are included in create_all.
    from app.voice import router as voice_router
    app.include_router(voice_router)

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
