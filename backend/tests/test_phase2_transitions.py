"""
Integration tests for Phase 2 email → application status transitions.

Tests call process_email_signal() directly (service layer), not via HTTP.
All DB state is rolled back per test via the conftest.py transaction fixture.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.models.user import User
from app.services.email_application_service import process_email_signal
from app.services.gemini_service import GeminiClassificationResult
from app.utils.company import normalize_company_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_company(db: Session, user: User, name: str) -> Company:
    company = Company(
        user_id=user.id,
        name=name,
        normalized_name=normalize_company_name(name),
    )
    db.add(company)
    db.flush()
    return company


def _make_application(
    db: Session,
    user: User,
    company: Company,
    status: ApplicationStatus,
    role: str = "Engineer",
    created_at: datetime | None = None,
) -> Application:
    app = Application(
        user_id=user.id,
        company_id=company.id,
        role=role,
        status=status,
    )
    db.add(app)
    db.flush()
    if created_at is not None:
        app.created_at = created_at
        db.flush()
    return app


def _make_email_account(db: Session, user: User) -> EmailAccount:
    account = EmailAccount(
        user_id=user.id,
        email=f"test_{uuid.uuid4().hex[:8]}@gmail.com",
        access_token="encrypted_access",
        refresh_token="encrypted_refresh",
    )
    db.add(account)
    db.flush()
    return account


def _make_raw_email(
    db: Session,
    email_account: EmailAccount,
    signal: str,
    confidence: float = 0.9,
) -> RawEmail:
    raw = RawEmail(
        email_account_id=email_account.id,
        gmail_message_id=f"msg_{uuid.uuid4().hex[:12]}",
        subject="redacted",
        sender="redacted@example.com",
        received_at=datetime.now(timezone.utc),
        body_snippet="redacted",
        gemini_signal=signal,
        gemini_confidence=confidence,
    )
    db.add(raw)
    db.flush()
    return raw


def _classification(
    signal: str,
    company: str | None,
    role: str | None = "Engineer",
    confidence: float = 0.9,
) -> GeminiClassificationResult:
    return GeminiClassificationResult(
        signal=signal,
        company=company,
        role=role,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# 1. APPLIED + INTERVIEW → INTERVIEW
# ---------------------------------------------------------------------------


def test_applied_to_interview(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.APPLIED)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.INTERVIEW
    assert raw.linked_application_id == app.id


# ---------------------------------------------------------------------------
# 2. Multiple APPLIED apps — transitions the most recent
# ---------------------------------------------------------------------------


def test_applied_to_interview_picks_most_recent(db: Session, test_user: User):
    now = datetime.now(timezone.utc)
    company = _make_company(db, test_user, "Acme Corp")
    older = _make_application(
        db, test_user, company, ApplicationStatus.APPLIED, role="Older Role",
        created_at=now - timedelta(hours=1),
    )
    newer = _make_application(
        db, test_user, company, ApplicationStatus.APPLIED, role="Newer Role",
        created_at=now,
    )
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", "Acme Corp")
    )

    db.refresh(older)
    db.refresh(newer)
    db.refresh(raw)
    assert newer.status == ApplicationStatus.INTERVIEW
    assert older.status == ApplicationStatus.APPLIED
    assert raw.linked_application_id == newer.id


# ---------------------------------------------------------------------------
# 3. INTERVIEW + OFFER → OFFER
# ---------------------------------------------------------------------------


def test_interview_to_offer(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.INTERVIEW)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "OFFER")

    process_email_signal(
        db, test_user.id, raw, _classification("OFFER", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.OFFER
    assert raw.linked_application_id == app.id


# ---------------------------------------------------------------------------
# 4. INTERVIEW + REJECTED → REJECTED
# ---------------------------------------------------------------------------


def test_interview_to_rejected(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.INTERVIEW)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "REJECTED")

    process_email_signal(
        db, test_user.id, raw, _classification("REJECTED", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.REJECTED
    assert raw.linked_application_id == app.id


# ---------------------------------------------------------------------------
# 5. APPLIED + REJECTED → REJECTED (existing chunk 12 logic)
# ---------------------------------------------------------------------------


def test_applied_to_rejected(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.APPLIED)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "REJECTED")

    process_email_signal(
        db, test_user.id, raw, _classification("REJECTED", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.REJECTED
    assert raw.linked_application_id == app.id


# ---------------------------------------------------------------------------
# 6. IN_PROGRESS + INTERVIEW → no-op (invalid transition)
# ---------------------------------------------------------------------------


def test_in_progress_interview_signal_is_noop(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(
        db, test_user, company, ApplicationStatus.IN_PROGRESS
    )
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.IN_PROGRESS
    # No APPLIED/INTERVIEW app found — INTERVIEW signal is a no-op, no app created
    assert raw.linked_application_id is None
    assert app.status == ApplicationStatus.IN_PROGRESS  # original app unchanged


# ---------------------------------------------------------------------------
# 7. OFFER + REJECTED signal → no-op (terminal state)
# ---------------------------------------------------------------------------


def test_offer_is_terminal(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.OFFER)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "REJECTED")

    process_email_signal(
        db, test_user.id, raw, _classification("REJECTED", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.OFFER
    assert raw.linked_application_id is None


# ---------------------------------------------------------------------------
# 8. REJECTED + INTERVIEW signal → no-op (terminal state)
# ---------------------------------------------------------------------------


def test_rejected_is_terminal(db: Session, test_user: User):
    company = _make_company(db, test_user, "Acme Corp")
    app = _make_application(db, test_user, company, ApplicationStatus.REJECTED)
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", "Acme Corp")
    )

    db.refresh(app)
    db.refresh(raw)
    assert app.status == ApplicationStatus.REJECTED
    assert raw.linked_application_id is None


# ---------------------------------------------------------------------------
# 9. classification.company is None → no-op, no DB writes
# ---------------------------------------------------------------------------


def test_null_company_is_noop(db: Session, test_user: User):
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", None)
    )

    db.refresh(raw)
    assert raw.linked_application_id is None


def test_empty_company_is_noop(db: Session, test_user: User):
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db, test_user.id, raw, _classification("INTERVIEW", "  ")
    )

    db.refresh(raw)
    assert raw.linked_application_id is None


# ---------------------------------------------------------------------------
# 10. INTERVIEW signal, no matching app → no-op
# ---------------------------------------------------------------------------


def test_interview_signal_no_match_is_noop(
    db: Session, test_user: User
):
    account = _make_email_account(db, test_user)
    raw = _make_raw_email(db, account, "INTERVIEW")

    process_email_signal(
        db,
        test_user.id,
        raw,
        _classification("INTERVIEW", "Brand New Corp", role="PM"),
    )

    db.refresh(raw)
    # No matching application exists — no-op, nothing created
    assert raw.linked_application_id is None

    count = db.scalar(
        select(func.count())
        .select_from(Application)
        .where(Application.user_id == test_user.id)
    )
    assert count == 0
