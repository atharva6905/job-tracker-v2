from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=255)
    location: str | None = Field(default=None, max_length=255)
    link: str | None = Field(default=None, max_length=2048)


class CompanyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    link: str | None = Field(default=None, max_length=2048)


class CompanyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    name: str
    normalized_name: str
    location: str | None
    link: str | None
    created_at: datetime
