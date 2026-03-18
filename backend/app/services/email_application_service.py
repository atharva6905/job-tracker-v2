"""
Email → Application logic.

Called by the poll worker after Gemini classifies an email with an actionable
signal (APPLIED / INTERVIEW / OFFER / REJECTED) at confidence >= 0.75.

=============================================================================
LOG HYGIENE: Never log subject, sender, body_snippet, or any user-authored text.
Permitted log fields only: gmail_message_id, email_account_id, gemini_signal,
gemini_confidence, action_taken, application_id, user_id, timestamps.
=============================================================================
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.raw_email import RawEmail
from app.services.company_service import find_or_create_company
from app.services.gemini_service import GeminiClassificationResult
from app.utils.company import normalize_company_name
from app.utils.logging import get_logger

_logger = get_logger("email_application_processor")


def process_email_signal(
    db: Session,
    user_id: UUID,
    raw_email: RawEmail,
    classification: GeminiClassificationResult,
) -> None:
    """
    Find or create an application matching the classified email, then apply
    the appropriate status transition.
    """
    signal = classification.signal
    company_name = classification.company

    if not company_name:
        _logger.warning(
            "No company extracted — skipping",
            extra={
                "gmail_message_id": raw_email.gmail_message_id,
                "gemini_signal": signal,
                "action_taken": "no_company_skip",
                "user_id": str(user_id),
            },
        )
        return

    normalized = normalize_company_name(company_name)
    target_status = ApplicationStatus(signal)

    # STEP 1 — Find matching application
    application = _find_matching_application(db, user_id, normalized, signal)

    # STEP 2 — Apply transition or create
    if application:
        _apply_transition(db, application, target_status, raw_email, user_id)
    else:
        _create_application(
            db, user_id, company_name, classification, raw_email, target_status
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_matching_application(
    db: Session,
    user_id: UUID,
    normalized_company: str,
    signal: str,
) -> Application | None:
    """Find an existing application that matches the email classification."""
    if signal == "APPLIED":
        # Primary: prefer IN_PROGRESS apps created by the extension (source_url set)
        app = db.scalar(
            select(Application)
            .join(Company, Application.company_id == Company.id)
            .where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.IN_PROGRESS,
                Company.normalized_name == normalized_company,
                Application.source_url.isnot(None),
            )
            .order_by(Application.created_at.desc())
        )
        if app:
            return app

        # Fallback: any IN_PROGRESS app by normalized company name
        return db.scalar(
            select(Application)
            .join(Company, Application.company_id == Company.id)
            .where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.IN_PROGRESS,
                Company.normalized_name == normalized_company,
            )
            .order_by(Application.created_at.desc())
        )

    # For INTERVIEW / OFFER / REJECTED: find APPLIED or INTERVIEW app
    return db.scalar(
        select(Application)
        .join(Company, Application.company_id == Company.id)
        .where(
            Application.user_id == user_id,
            Application.status.in_(
                [ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW]
            ),
            Company.normalized_name == normalized_company,
        )
        .order_by(Application.created_at.desc())
    )


def _apply_transition(
    db: Session,
    application: Application,
    target_status: ApplicationStatus,
    raw_email: RawEmail,
    user_id: UUID,
) -> None:
    """Apply the status transition on an existing application."""
    current = application.status

    # IN_PROGRESS → APPLIED — wired
    if (
        current == ApplicationStatus.IN_PROGRESS
        and target_status == ApplicationStatus.APPLIED
    ):
        application.status = ApplicationStatus.APPLIED
        application.date_applied = (
            raw_email.received_at.date() if raw_email.received_at else None
        )
        raw_email.linked_application_id = application.id
        db.commit()
        _logger.info(
            "Application status updated",
            extra={
                "action_taken": "status_updated",
                "from": "IN_PROGRESS",
                "to": "APPLIED",
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    # APPLIED → REJECTED — wired
    if (
        current == ApplicationStatus.APPLIED
        and target_status == ApplicationStatus.REJECTED
    ):
        application.status = ApplicationStatus.REJECTED
        raw_email.linked_application_id = application.id
        db.commit()
        _logger.info(
            "Application status updated",
            extra={
                "action_taken": "status_updated",
                "from": "APPLIED",
                "to": "REJECTED",
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    # Phase 2 transitions — not wired yet
    if current == ApplicationStatus.APPLIED and target_status == ApplicationStatus.INTERVIEW:
        _logger.info(
            "Phase 2 transition — not wired yet",
            extra={
                "action_taken": "no_op_phase2",
                "signal": target_status.value,
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    if current == ApplicationStatus.INTERVIEW and target_status in {
        ApplicationStatus.OFFER,
        ApplicationStatus.REJECTED,
    }:
        _logger.info(
            "Phase 2 transition — not wired yet",
            extra={
                "action_taken": "no_op_phase2",
                "signal": target_status.value,
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    # Invalid transition — no-op, never raise
    _logger.info(
        "Invalid transition — no-op",
        extra={
            "action_taken": "no_op_invalid_transition",
            "reason": f"{current.value} -> {target_status.value} is not valid",
            "application_id": str(application.id),
            "user_id": str(user_id),
        },
    )


def _create_application(
    db: Session,
    user_id: UUID,
    company_name: str,
    classification: GeminiClassificationResult,
    raw_email: RawEmail,
    target_status: ApplicationStatus,
) -> None:
    """Create a new application when no matching one exists."""
    company = find_or_create_company(db, user_id, company_name)

    application = Application(
        user_id=user_id,
        company_id=company.id,
        role=classification.role or "Unknown",
        status=target_status,
        date_applied=(
            raw_email.received_at.date()
            if target_status == ApplicationStatus.APPLIED and raw_email.received_at
            else None
        ),
    )
    db.add(application)
    db.flush()

    raw_email.linked_application_id = application.id
    db.commit()

    _logger.info(
        "Application created from email",
        extra={
            "action_taken": "application_created",
            "status": target_status.value,
            "application_id": str(application.id),
            "user_id": str(user_id),
        },
    )
