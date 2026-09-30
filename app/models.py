from datetime import date, datetime, timezone
from uuid import uuid4
from sqlalchemy import CheckConstraint, Date, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base
from app.schemas import STATES


def utcnow():
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"
    __table_args__ = (
        CheckConstraint("length(first_name) BETWEEN 1 AND 50", name="ck_first_name_length"),
        CheckConstraint("length(last_name) BETWEEN 1 AND 50", name="ck_last_name_length"),
        CheckConstraint("date_of_birth <= CURRENT_DATE", name="ck_dob_not_future"),
        CheckConstraint("sex IN ('Male','Female','Other','Decline to Answer')", name="ck_sex"),
        CheckConstraint("length(phone_number) = 10", name="ck_phone_length"),
        CheckConstraint("length(address_line_1) BETWEEN 1 AND 200", name="ck_address_length"),
        CheckConstraint("length(city) BETWEEN 1 AND 100", name="ck_city_length"),
        CheckConstraint("state IN (" + ",".join(f"'{s}'" for s in sorted(STATES)) + ")", name="ck_state"),
        CheckConstraint("length(zip_code) IN (5,10)", name="ck_zip_length"),
        CheckConstraint("emergency_contact_phone IS NULL OR length(emergency_contact_phone) = 10", name="ck_emergency_phone_length"),
        CheckConstraint("length(preferred_language) BETWEEN 1 AND 50", name="ck_language_length"),
        Index("ix_patients_active_created", "deleted_at", "created_at"),
    )
    patient_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sex: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    address_line_1: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    address_line_2: Mapped[str | None] = mapped_column(String(200))
    insurance_provider: Mapped[str | None] = mapped_column(String(100))
    insurance_member_id: Mapped[str | None] = mapped_column(String(100))
    preferred_language: Mapped[str] = mapped_column(String(50), default="English", nullable=False)
    emergency_contact_name: Mapped[str | None] = mapped_column(String(100))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
