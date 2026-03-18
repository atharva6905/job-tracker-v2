import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class EmailAccountResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    created_at: datetime
