"""Integration tests for email → application create/update logic."""

import uuid
from datetime import datetime, timezone

import pytest
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
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def email_account(db: Session, test_user: User) -> EmailAccount:
    account = EmailAccount(
        user_id=test_user.id,
        email="test@gmail.com",
        access_token="encrypted_access",
        refresh_token="encrypted_refresh",
    )
    db.add(account)
    db.flush()
    return account


def _make_raw_email(
    db: Session,
    email_account: EmailAccount,
    *,
    gmail_message_id: str | None = None,
    received_at: datetime | None = None,
    subject: str = "Test Subject",
    gemini_signal: str = "APPLIED",
    gemini_confidence: float = 0.95,
) -> RawEmail:
    raw_email = RawEmail(
        email_account_id=email_account.id,
        gmail_message_id=gmail_message_id or f"msg_{uuid.uuid4().hex[:12]}",
        subject=subject,
        sender="noreply@company.com",
        received_at=received_at or datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
        body_snippet="Thank you for applying...",
        gemini_signal=gemini_signal,
        gemini_confidence=gemini_confidence,
    )
    db.add(raw_email)
    db.flush()
    return raw_email


def _make_company(db: Session, user_id, name: str = "Acme Corp") -> Company:
    company = Company(
        user_id=user_id,
        name=name,
        normalized_name=normalize_company_name(name),
    )
    db.add(company)
    db.flush()
    return company


def _make_application(
    db: Session,
    user_id,
    company_id,
    status: ApplicationStatus,
    *,
    source_url: str | None = None,
    ats_job_id: str | None = None,
    role: str = "Software Engineer",
) -> Application:
    application = Application(
        user_id=user_id,
        company_id=company_id,
        role=role,
        status=status,
        source_url=source_url,
        ats_job_id=ats_job_id,
    )
    db.add(application)
    db.flush()
    return application


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProcessEmailSignal:
    def test_in_progress_to_applied(self, db, test_user, email_account):
        """IN_PROGRESS + APPLIED signal → transitions to APPLIED, date_applied = received_at."""
        company = _make_company(db, test_user.id)
        app = _make_application(db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS)
        received = datetime(2025, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        raw_email = _make_raw_email(db, email_account, received_at=received)

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED
        assert app.date_applied == received.date()
        assert raw_email.linked_application_id == app.id

    def test_dedup_prefers_source_url(self, db, test_user, email_account):
        """When multiple IN_PROGRESS apps exist, prefer the one with source_url (extension-created)."""
        company = _make_company(db, test_user.id)
        app_no_url = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        app_with_url = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            source_url="https://example.com/jobs/123",
        )
        raw_email = _make_raw_email(db, email_account)

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app_with_url)
        db.refresh(app_no_url)
        assert app_with_url.status == ApplicationStatus.APPLIED
        assert app_no_url.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id == app_with_url.id

    def test_no_match_is_no_op(self, db, test_user, email_account):
        """No matching application + APPLIED signal → no-op. No new application created."""
        raw_email = _make_raw_email(db, email_account)

        classification = GeminiClassificationResult(
            company="New Corp",
            role="Data Scientist",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        count = db.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.user_id == test_user.id)
        )
        assert count == 0  # no application created
        assert raw_email.linked_application_id is None  # not linked

    def test_company_normalization_google_llc(self, db, test_user, email_account):
        """'Google LLC' normalizes to 'google' and transitions the existing 'Google' IN_PROGRESS app."""
        company = _make_company(db, test_user.id, name="Google")
        app = _make_application(db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS)
        raw_email = _make_raw_email(db, email_account)

        classification = GeminiClassificationResult(
            company="Google LLC",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.85,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        # No new company should have been created
        count = db.scalar(
            select(func.count())
            .select_from(Company)
            .where(Company.user_id == test_user.id)
        )
        assert count == 1

        # The existing IN_PROGRESS app should now be APPLIED
        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED
        assert raw_email.linked_application_id == app.id

    def test_applied_interview_transitions(self, db, test_user, email_account):
        """APPLIED + INTERVIEW signal → status becomes INTERVIEW (Phase 2 wired)."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
        )
        raw_email = _make_raw_email(
            db, email_account, gemini_signal="INTERVIEW", gemini_confidence=0.90,
        )

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Software Engineer",
            signal="INTERVIEW",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        db.refresh(raw_email)
        assert app.status == ApplicationStatus.INTERVIEW
        assert raw_email.linked_application_id == app.id

    def test_duplicate_gmail_message_id_dedup(self, db, test_user, email_account):
        """Duplicate gmail_message_id is not processed twice (dedup in poll worker).

        The poll worker checks gmail_message_id uniqueness before calling
        process_email_signal, so two emails with the same ID never both reach
        this service.  Here we verify the database constraint: inserting a
        second RawEmail with the same gmail_message_id raises IntegrityError.
        """
        from sqlalchemy.exc import IntegrityError

        msg_id = "msg_duplicate_123"
        _make_raw_email(db, email_account, gmail_message_id=msg_id)

        with pytest.raises(IntegrityError):
            _make_raw_email(db, email_account, gmail_message_id=msg_id)
        db.rollback()

    def test_date_applied_is_received_at_not_now(self, db, test_user, email_account):
        """date_applied must be the email's received_at, not the current timestamp."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )

        past = datetime(2024, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
        raw_email = _make_raw_email(db, email_account, received_at=past)

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.date_applied == past.date()  # 2024-01-15, not today

    def test_applied_rejected_wired(self, db, test_user, email_account):
        """APPLIED + REJECTED signal → transitions to REJECTED."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
        )
        raw_email = _make_raw_email(
            db, email_account, gemini_signal="REJECTED", gemini_confidence=0.92,
        )

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Software Engineer",
            signal="REJECTED",
            confidence=0.92,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.REJECTED
        assert raw_email.linked_application_id == app.id

    def test_no_company_extracted_skips(self, db, test_user, email_account):
        """When Gemini returns no company name, process_email_signal is a no-op."""
        raw_email = _make_raw_email(db, email_account)

        classification = GeminiClassificationResult(
            company=None,
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        count = db.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.user_id == test_user.id)
        )
        assert count == 0

    def test_no_match_safety_net_logs_no_op(self, db, test_user, email_account):
        """E1: Safety net — when process_email_signal finds no match, it is a no-op (no crash, no app created)."""
        raw_email = _make_raw_email(db, email_account)

        classification = GeminiClassificationResult(
            company="Nonexistent Corp",
            role="Engineer",
            signal="INTERVIEW",
            confidence=0.90,
        )

        # No application exists for "Nonexistent Corp" in any state
        process_email_signal(db, test_user.id, raw_email, classification)

        count = db.scalar(
            select(func.count())
            .select_from(Application)
            .where(Application.user_id == test_user.id)
        )
        assert count == 0
        assert raw_email.linked_application_id is None

    def test_ats_job_id_match_transitions_even_when_company_differs(
        self, db, test_user, email_account
    ):
        """ATS job ID match takes priority over company name — transitions even when company differs."""
        acme = _make_company(db, test_user.id, name="Acme Corp")
        app_with_id = _make_application(
            db, test_user.id, acme.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Cashier_R2000648316",
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Cashier_R2000648316",
        )
        # Different company — would NOT match via company name fallback
        other_co = _make_company(db, test_user.id, name="Different Corp")
        app_other = _make_application(
            db, test_user.id, other_co.id, ApplicationStatus.IN_PROGRESS,
        )

        raw_email = _make_raw_email(
            db, email_account, subject="Your application for R2000648316 has been received",
        )

        classification = GeminiClassificationResult(
            company="Different Corp",
            role="Cashier",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app_with_id)
        db.refresh(app_other)
        assert app_with_id.status == ApplicationStatus.APPLIED
        assert app_other.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id == app_with_id.id

    def test_ats_job_id_falls_through_to_source_url_when_no_r_number(
        self, db, test_user, email_account
    ):
        """No R-number in subject → falls through to source_url dedup."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Cashier_R2000648316",
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Cashier_R2000648316",
        )

        raw_email = _make_raw_email(
            db, email_account, subject="Thanks for applying to Acme Corp!",
        )

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Cashier",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED
        assert raw_email.linked_application_id == app.id

    def test_ats_job_id_falls_through_to_company_when_no_match(
        self, db, test_user, email_account
    ):
        """R-number in subject doesn't match any app → falls through to company name dedup."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Cashier_R1111111",
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Cashier_R1111111",
        )

        raw_email = _make_raw_email(
            db, email_account, subject="Your application for R9999999 has been received",
        )

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Engineer",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED
        assert raw_email.linked_application_id == app.id
