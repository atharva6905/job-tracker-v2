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
    Find an existing application matching the classified email and apply the
    appropriate status transition. If no matching application exists, this is
    a no-op.
    """
    signal = classification.signal
    company_name = classification.company

    if not company_name or not company_name.strip():
        _logger.warning(
            "No company extracted — skipping",
            extra={
                "gmail_message_id": raw_email.gmail_message_id,
                "gemini_signal": signal,
                "action_taken": "no_op_null_company",
                "user_id": str(user_id),
            },
        )
        return

    normalized = normalize_company_name(company_name)
    target_status = ApplicationStatus(signal)

    # STEP 1 — Find matching application
    application = _find_matching_application(db, user_id, normalized, signal)

    # STEP 2 — Apply transition or no-op
    if application:
        _apply_transition(db, application, target_status, raw_email, user_id)
    else:
        # No matching active application found — no-op.
        # The poll worker's fine gate should have caught this already.
        # This acts as a safety net for PARSE_ERROR retries.
        _logger.info(
            "No matching application found — no-op",
            extra={
                "gmail_message_id": raw_email.gmail_message_id,
                "gemini_signal": signal,
                "action_taken": "no_in_progress_match",
                "user_id": str(user_id),
            },
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

    # For INTERVIEW / OFFER / REJECTED: prefer transitional apps (APPLIED, INTERVIEW)
    app = db.scalar(
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
    if app:
        return app

    # Fallback: match terminal-state apps so _apply_transition can log no-op
    return db.scalar(
        select(Application)
        .join(Company, Application.company_id == Company.id)
        .where(
            Application.user_id == user_id,
            Application.status.in_(
                [ApplicationStatus.OFFER, ApplicationStatus.REJECTED]
            ),
            Company.normalized_name == normalized_company,
        )
        .order_by(Application.created_at.desc())
    )


_VALID_TRANSITIONS = {
    (ApplicationStatus.IN_PROGRESS, ApplicationStatus.APPLIED),
    (ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW),
    (ApplicationStatus.APPLIED, ApplicationStatus.REJECTED),
    (ApplicationStatus.INTERVIEW, ApplicationStatus.OFFER),
    (ApplicationStatus.INTERVIEW, ApplicationStatus.REJECTED),
}

_TERMINAL_STATES = {ApplicationStatus.OFFER, ApplicationStatus.REJECTED}


def _apply_transition(
    db: Session,
    application: Application,
    target_status: ApplicationStatus,
    raw_email: RawEmail,
    user_id: UUID,
) -> None:
    """Apply the status transition on an existing application."""
    current = application.status

    # Terminal states — no transitions out
    if current in _TERMINAL_STATES:
        _logger.info(
            "Terminal state — no-op",
            extra={
                "action_taken": "no_op_terminal_state",
                "current_status": current.value,
                "signal": target_status.value,
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    # Invalid transition — no-op, never raise
    if (current, target_status) not in _VALID_TRANSITIONS:
        _logger.info(
            "Invalid transition — no-op",
            extra={
                "action_taken": "no_op_invalid_transition",
                "signal": target_status.value,
                "application_id": str(application.id),
                "user_id": str(user_id),
            },
        )
        return

    # Apply valid transition
    application.status = target_status

    # IN_PROGRESS → APPLIED sets date_applied from the confirmation email
    if (
        current == ApplicationStatus.IN_PROGRESS
        and target_status == ApplicationStatus.APPLIED
    ):
        application.date_applied = (
            raw_email.received_at.date() if raw_email.received_at else None
        )

    raw_email.linked_application_id = application.id
    db.commit()

    _logger.info(
        "Application status updated",
        extra={
            "action_taken": "status_updated",
            "from": current.value,
            "to": target_status.value,
            "application_id": str(application.id),
            "user_id": str(user_id),
        },
    )
