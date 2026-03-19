from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RawEmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subject: str | None
    sender: str | None
    received_at: datetime | None
    gemini_signal: str | None
    gemini_confidence: float | None
    body_snippet: str | None
