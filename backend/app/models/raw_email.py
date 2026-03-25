import uuid
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RawEmail(Base):
    __tablename__ = "raw_emails"
    __table_args__ = (
        UniqueConstraint("gmail_message_id", name="uq_raw_emails_gmail_message_id"),
        Index(
            "ix_raw_emails_email_account_id_received_at",
            "email_account_id",
            "received_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("email_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    gmail_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    body_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemini_signal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gemini_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    gemini_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linked_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
