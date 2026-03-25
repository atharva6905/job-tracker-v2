import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Text, TIMESTAMP, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class JobDescription(Base):
    __tablename__ = "job_descriptions"
    __table_args__ = (
        UniqueConstraint(
            "application_id", name="uq_job_descriptions_application_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    structured_jd: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
