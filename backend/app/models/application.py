import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Date, Enum, ForeignKey, Index, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApplicationStatus(str, enum.Enum):
    IN_PROGRESS = "IN_PROGRESS"
    APPLIED = "APPLIED"
    INTERVIEW = "INTERVIEW"
    OFFER = "OFFER"
    REJECTED = "REJECTED"


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        Index("ix_applications_user_id_status", "user_id", "status"),
        Index("ix_applications_user_id_date_applied", "user_id", "date_applied"),
        Index("ix_applications_company_id", "company_id"),
        Index("ix_applications_user_id_source_url", "user_id", "source_url"),
        Index("ix_applications_user_id_ats_job_id", "user_id", "ats_job_id"),
        Index("ix_applications_user_id_workday_tenant", "user_id", "workday_tenant"),
        Index("ix_applications_user_id_deleted_at", "user_id", "deleted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="applicationstatus"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    ats_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    workday_tenant: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date_applied: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), nullable=True
    )
