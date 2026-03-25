from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.application import ApplicationStatus


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_id: UUID
    role: str = Field(max_length=255)
    notes: str | None = Field(default=None, max_length=5000)


class ApplicationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=5000)
    # IN_PROGRESS excluded — only settable by POST /extension/capture
    status: Literal["APPLIED", "INTERVIEW", "OFFER", "REJECTED"] | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    company_id: UUID
    role: str
    status: ApplicationStatus
    source_url: str | None
    date_applied: date | None
    notes: str | None
    created_at: datetime


class JobDescriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    raw_text: str
    captured_at: datetime
    structured_jd: dict | None = None
