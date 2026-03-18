import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, Index, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RoundType(str, enum.Enum):
    PHONE = "PHONE"
    TECHNICAL = "TECHNICAL"
    BEHAVIORAL = "BEHAVIORAL"
    SYSTEM_DESIGN = "SYSTEM_DESIGN"
    FINAL = "FINAL"
    OTHER = "OTHER"


class InterviewOutcome(str, enum.Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    PENDING = "PENDING"


class Interview(Base):
    __tablename__ = "interviews"
    __table_args__ = (Index("ix_interviews_application_id", "application_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    round_type: Mapped[RoundType] = mapped_column(
        Enum(RoundType, name="roundtype"), nullable=False
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
    outcome: Mapped[InterviewOutcome | None] = mapped_column(
        Enum(InterviewOutcome, name="interviewoutcome"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
