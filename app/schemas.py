"""One validation contract shared by REST, dashboard and voice tools."""
import re
from datetime import date, datetime
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

STATES = frozenset("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())
SEX_VALUES = ("Male", "Female", "Other", "Decline to Answer")
Sex = Literal["Male", "Female", "Other", "Decline to Answer"]
Name = Annotated[str, Field(min_length=1, max_length=50)]


def parse_dob(value):
    if isinstance(value, datetime):
        raise ValueError("Use a date in MM/DD/YYYY format")
    if isinstance(value, date):
        result = value
    elif isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
            fmt = "%m/%d/%Y"
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            fmt = "%Y-%m-%d"
        else:
            raise ValueError("Use MM/DD/YYYY (for example 03/14/1990)")
        try:
            result = datetime.strptime(value, fmt).date()
        except ValueError:
            raise ValueError("Date of birth must be a real calendar date") from None
    else:
        raise ValueError("Use a date in MM/DD/YYYY format")
    if result > date.today():
        raise ValueError("Date of birth cannot be in the future")
    return result


def normalize_phone(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Phone number must be a string of 10 US digits")
    value = value.strip()
    if not re.fullmatch(r"[0-9()+.\s-]+", value):
        raise ValueError("Phone number must contain exactly 10 US digits")
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("Phone number must contain exactly 10 US digits")
    return digits


class PatientFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    first_name: Name
    last_name: Name
    date_of_birth: date
    sex: Sex
    phone_number: str
    address_line_1: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str
    zip_code: str
    email: EmailStr | None = Field(default=None, max_length=254)
    address_line_2: str | None = Field(default=None, max_length=200)
    insurance_provider: str | None = Field(default=None, max_length=100)
    insurance_member_id: str | None = Field(default=None, max_length=100)
    preferred_language: str = Field(default="English", min_length=1, max_length=50)
    emergency_contact_name: str | None = Field(default=None, max_length=100)
    emergency_contact_phone: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def valid_unicode(cls, value):
        if isinstance(value, str):
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise ValueError("Use valid Unicode text") from None
        return value

    @field_validator("first_name", "last_name")
    @classmethod
    def valid_name(cls, value):
        if not any(char.isalpha() for char in value) or any(not (char.isalpha() or char in "-'") for char in value):
            raise ValueError("Use alphabetic characters, hyphens, or apostrophes only")
        return value

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def valid_date(cls, value):
        return parse_dob(value)

    @field_validator("phone_number", "emergency_contact_phone", mode="before")
    @classmethod
    def valid_phone(cls, value):
        return normalize_phone(value)

    @field_validator("state")
    @classmethod
    def valid_state(cls, value):
        value = value.upper()
        if value not in STATES:
            raise ValueError("Use a valid two-letter US state code or DC")
        return value

    @field_validator("zip_code")
    @classmethod
    def valid_zip(cls, value):
        if not re.fullmatch(r"[0-9]{5}(?:-[0-9]{4})?", value):
            raise ValueError("Use a five-digit ZIP code or ZIP+4")
        return value

    @field_validator("insurance_member_id")
    @classmethod
    def valid_member_id(cls, value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9]+", value):
            raise ValueError("Insurance member ID must be alphanumeric")
        return value

    @field_validator("emergency_contact_name")
    @classmethod
    def valid_emergency_name(cls, value):
        if value is not None and (not any(c.isalpha() for c in value) or any(not (c.isalpha() or c in "-' ") for c in value)):
            raise ValueError("Use letters, spaces, hyphens, or apostrophes for contact name")
        return value

    @field_validator("email", "address_line_2", "insurance_provider", "insurance_member_id", "emergency_contact_name", "emergency_contact_phone", mode="before")
    @classmethod
    def blank_optional(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class PatientCreate(PatientFields):
    pass


# Partial update inherits exactly the same field validators, then the service validates
# the merged complete record. Optional fields may be explicitly cleared with null.
class PatientUpdate(PatientFields):
    first_name: Name | None = None
    last_name: Name | None = None
    date_of_birth: date | None = None
    sex: Sex | None = None
    phone_number: str | None = None
    address_line_1: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: str | None = None
    zip_code: str | None = None
    preferred_language: str | None = Field(default=None, min_length=1, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def required_cannot_be_null(cls, value):
        if isinstance(value, dict):
            required = {"first_name", "last_name", "date_of_birth", "sex", "phone_number", "address_line_1", "city", "state", "zip_code", "preferred_language"}
            for key in required & value.keys():
                if value[key] is None:
                    raise ValueError(f"{key} cannot be null")
        return value
