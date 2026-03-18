from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.interview import InterviewOutcome, RoundType


class InterviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_type: RoundType
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=5000)


class InterviewUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    round_type: RoundType | None = None
    scheduled_at: datetime | None = None
    outcome: InterviewOutcome | None = None
    notes: str | None = Field(default=None, max_length=5000)


class InterviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    application_id: UUID
    round_type: RoundType
    scheduled_at: datetime | None
    outcome: InterviewOutcome | None
    notes: str | None
    created_at: datetime
