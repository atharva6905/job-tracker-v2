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

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.services.gemini_service import ACTIONABLE_SIGNALS, GeminiClassificationResult
from app.utils.company import normalize_company_name
from app.utils.logging import get_logger
from app.utils.workday import extract_tenant_from_sender

_logger = get_logger("email_application_processor")

_ATS_JOB_ID_RE = re.compile(r"\bR\d{7,}\b")


def extract_ats_job_id(subject: str) -> str | None:
    """Extract a Workday R-number (e.g. R2000648316) from an email subject."""
    match = _ATS_JOB_ID_RE.search(subject)
    return match.group(0) if match else None


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
        # No company extracted — but if the subject contains an R-number,
        # the ats_job_id lookup can still match without a company name.
        if not extract_ats_job_id(raw_email.subject or ""):
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

    normalized = normalize_company_name(company_name) if company_name else ""
    target_status = ApplicationStatus(signal)

    # STEP 1 — Find matching application
    application = _find_matching_application(
        db, user_id, normalized, signal, raw_email,
        classification_role=classification.role,
    )

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


def replay_matched_emails(db: Session, application: Application) -> None:
    """Replay previously classified but unlinked emails against a new application.

    Called immediately after POST /extension/capture creates a new IN_PROGRESS
    application. Finds emails that match this application (by R-number, Workday
    tenant, or normalized company name) and replays them in chronological order
    to fast-forward the status.
    """
    user_id = application.user_id

    # Load company for normalized name matching
    company = db.scalar(
        select(Company).where(Company.id == application.company_id)
    )
    normalized_company = company.normalized_name if company else ""

    # Extract R-number from ats_job_id if present
    r_match = _ATS_JOB_ID_RE.search(application.ats_job_id or "")
    r_number = r_match.group(0) if r_match else None

    tenant = application.workday_tenant

    # Query all unlinked actionable emails for this user
    candidates = db.scalars(
        select(RawEmail)
        .join(EmailAccount, RawEmail.email_account_id == EmailAccount.id)
        .where(
            EmailAccount.user_id == user_id,
            RawEmail.linked_application_id.is_(None),
            RawEmail.gemini_signal.in_(ACTIONABLE_SIGNALS),
            RawEmail.gemini_confidence >= 0.75,
        )
        .order_by(RawEmail.received_at.asc())
    ).all()

    # Filter in Python for any of the 3 match conditions
    seen_ids: set[str] = set()
    matched: list[RawEmail] = []
    for email in candidates:
        if email.gmail_message_id in seen_ids:
            continue

        hit = False
        # Condition 1: R-number in subject
        if r_number and email.subject and r_number in email.subject:
            hit = True
        # Condition 2: Workday tenant in sender
        if not hit and tenant and email.sender:
            if f"{tenant}@myworkday" in email.sender.lower():
                hit = True
        # Condition 3: Normalized company name
        if not hit and email.gemini_company and normalized_company:
            if normalize_company_name(email.gemini_company) == normalized_company:
                hit = True

        if hit:
            seen_ids.add(email.gmail_message_id)
            matched.append(email)

    replayed = 0
    for raw_email in matched:
        classification = GeminiClassificationResult(
            company=raw_email.gemini_company,
            role=None,
            signal=raw_email.gemini_signal,
            confidence=raw_email.gemini_confidence,
        )
        try:
            process_email_signal(db, user_id, raw_email, classification)
            replayed += 1
        except Exception:
            _logger.warning(
                "Replay failed for email",
                exc_info=True,
                extra={
                    "gmail_message_id": raw_email.gmail_message_id,
                    "application_id": str(application.id),
                    "action_taken": "replay_error",
                },
            )

    if replayed:
        _logger.info(
            "Replayed matched emails for re-tracked application",
            extra={
                "application_id": str(application.id),
                "replayed_count": replayed,
                "action_taken": "replay_complete",
            },
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _find_matching_application(
    db: Session,
    user_id: UUID,
    normalized_company: str,
    signal: str,
    raw_email: RawEmail,
    *,
    classification_role: str | None = None,
) -> Application | None:
    """Find an existing application that matches the email classification.

    Priority chain:
      0 — ATS job ID (R-number in subject)
      1 — Workday tenant (sender email → application.workday_tenant)
      2 — source_url + normalized company (extension-created apps)
      3 — normalized company name only
      4 — Role token Jaccard similarity (>= 0.7, last 14 days, exactly 1 match)
    """
    if signal == "APPLIED":
        # Priority 0: match by ATS job ID (strongest signal — ignores company name)
        r_number = extract_ats_job_id(raw_email.subject or "")
        if r_number:
            app = db.scalar(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.status == ApplicationStatus.IN_PROGRESS,
                    Application.ats_job_id.isnot(None),
                    Application.ats_job_id.contains(r_number),
                )
                .order_by(Application.created_at.desc())
            )
            if app:
                return app

        # Priority 1: Workday tenant match
        sender_tenant = extract_tenant_from_sender(raw_email.sender)
        if sender_tenant:
            tenant_apps = db.scalars(
                select(Application).where(
                    Application.user_id == user_id,
                    Application.status == ApplicationStatus.IN_PROGRESS,
                    Application.workday_tenant == sender_tenant,
                )
                .order_by(Application.created_at.desc())
            ).all()
            if len(tenant_apps) == 1:
                return tenant_apps[0]
            # Multiple matches: fall through — don't guess

        # Priority 2: prefer IN_PROGRESS apps created by the extension (source_url set)
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

        # Priority 3: any IN_PROGRESS app by normalized company name
        app = db.scalar(
            select(Application)
            .join(Company, Application.company_id == Company.id)
            .where(
                Application.user_id == user_id,
                Application.status == ApplicationStatus.IN_PROGRESS,
                Company.normalized_name == normalized_company,
            )
            .order_by(Application.created_at.desc())
        )
        if app:
            return app

        # Priority 4: role token Jaccard similarity (last resort)
        return _jaccard_fallback(
            db, user_id, classification_role,
            [ApplicationStatus.IN_PROGRESS],
        )

    # For INTERVIEW / OFFER / REJECTED: prefer transitional apps (APPLIED, INTERVIEW)

    # Priority 1: Workday tenant match (transitional states)
    sender_tenant = extract_tenant_from_sender(raw_email.sender)
    if sender_tenant:
        tenant_apps = db.scalars(
            select(Application).where(
                Application.user_id == user_id,
                Application.status.in_(
                    [ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW]
                ),
                Application.workday_tenant == sender_tenant,
            )
            .order_by(Application.created_at.desc())
        ).all()
        if len(tenant_apps) == 1:
            return tenant_apps[0]

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
    app = db.scalar(
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
    if app:
        return app

    # Priority 4: role token Jaccard similarity (last resort)
    return _jaccard_fallback(
        db, user_id, classification_role,
        [ApplicationStatus.APPLIED, ApplicationStatus.INTERVIEW],
    )


def _jaccard_fallback(
    db: Session,
    user_id: UUID,
    classification_role: str | None,
    statuses: list[ApplicationStatus],
) -> Application | None:
    """Last-resort matching by role token Jaccard similarity.

    Only fires when all higher priorities fail. Requires exactly one match
    with Jaccard >= 0.7 among apps created in the last 14 days.
    Multiple matches = no-op (ambiguous).
    """
    if not classification_role:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)
    recent_apps = db.scalars(
        select(Application).where(
            Application.user_id == user_id,
            Application.status.in_(statuses),
            Application.created_at >= cutoff,
        )
    ).all()
    role_tokens = set(classification_role.lower().split())
    matches = [
        app for app in recent_apps
        if _jaccard_similarity(role_tokens, set(app.role.lower().split())) >= 0.7
    ]
    if len(matches) == 1:
        return matches[0]
    return None


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
