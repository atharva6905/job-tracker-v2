import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GmailOAuthState(Base):
    __tablename__ = "gmail_oauth_states"

    __table_args__ = (
        Index("ix_gmail_oauth_states_user_id", "user_id"),
        Index("ix_gmail_oauth_states_expires_at", "expires_at"),
    )

    state_token: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    code_verifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
