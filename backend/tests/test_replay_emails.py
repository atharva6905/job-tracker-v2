"""Integration tests for replay_matched_emails — email fast-forward on re-track."""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.models.user import User
from app.services.email_application_service import replay_matched_emails
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
    sender: str = "noreply@company.com",
    gemini_signal: str = "APPLIED",
    gemini_confidence: float = 0.95,
    gemini_company: str | None = "Acme Corp",
    linked_application_id: uuid.UUID | None = None,
) -> RawEmail:
    raw_email = RawEmail(
        email_account_id=email_account.id,
        gmail_message_id=gmail_message_id or f"msg_{uuid.uuid4().hex[:12]}",
        subject=subject,
        sender=sender,
        received_at=received_at or datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
        body_snippet="Thank you for applying...",
        gemini_signal=gemini_signal,
        gemini_confidence=gemini_confidence,
        gemini_company=gemini_company,
        linked_application_id=linked_application_id,
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
    workday_tenant: str | None = None,
    role: str = "Software Engineer",
) -> Application:
    application = Application(
        user_id=user_id,
        company_id=company_id,
        role=role,
        status=status,
        source_url=source_url,
        ats_job_id=ats_job_id,
        workday_tenant=workday_tenant,
    )
    db.add(application)
    db.flush()
    return application


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReplayMatchedEmails:
    def test_r_number_match_advances_to_applied(
        self, db, test_user, email_account
    ):
        """Re-track with matching R-number in subject → advances to APPLIED."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Cashier_R2000648316",
            source_url="https://acme.wd5.myworkdayjobs.com/job/Cashier_R2000648316",
        )
        _make_raw_email(
            db, email_account,
            subject="Your application for R2000648316 has been received",
            gemini_company="Acme Corp",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED

    def test_tenant_match_advances(self, db, test_user, email_account):
        """Re-track with matching Workday tenant → advances to APPLIED."""
        company = _make_company(db, test_user.id, "Meredith")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith",
        )
        _make_raw_email(
            db, email_account,
            sender="meredith@myworkday.com",
            gemini_company="People Inc.",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED

    def test_company_name_match_with_normalization(
        self, db, test_user, email_account
    ):
        """Re-track with normalized company name match → advances to APPLIED."""
        company = _make_company(db, test_user.id, "Acme Corp")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        # gemini_company has legal suffix that normalizes to same name
        _make_raw_email(
            db, email_account,
            gemini_company="Acme Corp LLC",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.APPLIED

    def test_already_linked_emails_not_replayed(
        self, db, test_user, email_account
    ):
        """Emails with linked_application_id set are skipped."""
        company = _make_company(db, test_user.id)
        other_app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
        )
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        # This email is already linked to another app
        _make_raw_email(
            db, email_account,
            gemini_company="Acme Corp",
            linked_application_id=other_app.id,
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS

    def test_below_threshold_not_replayed(self, db, test_user, email_account):
        """Emails with confidence below 0.75 are not replayed."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        _make_raw_email(
            db, email_account,
            gemini_signal="BELOW_THRESHOLD",
            gemini_confidence=0.60,
            gemini_company="Acme Corp",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS

    def test_no_matching_emails_stays_in_progress(
        self, db, test_user, email_account
    ):
        """No matching unlinked emails → stays IN_PROGRESS, no error."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        # Email for a different company
        _make_raw_email(
            db, email_account,
            gemini_company="Totally Different Corp",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS

    def test_multi_email_replay_advances_to_interview(
        self, db, test_user, email_account
    ):
        """Two emails (APPLIED then INTERVIEW) → advances through to INTERVIEW."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )
        # APPLIED email first (earlier timestamp)
        _make_raw_email(
            db, email_account,
            received_at=datetime(2025, 6, 15, 10, 0, 0, tzinfo=timezone.utc),
            gemini_signal="APPLIED",
            gemini_company="Acme Corp",
        )
        # INTERVIEW email second (later timestamp)
        _make_raw_email(
            db, email_account,
            received_at=datetime(2025, 6, 20, 14, 0, 0, tzinfo=timezone.utc),
            gemini_signal="INTERVIEW",
            gemini_company="Acme Corp",
        )

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.INTERVIEW

    def test_idempotent_capture_does_not_replay(
        self, db, test_user, email_account, client, auth_headers
    ):
        """Idempotent capture (same source_url, app exists) → replay NOT called."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            source_url="https://acme.wd5.myworkdayjobs.com/job/Engineer_R1234567",
        )
        # Unlinked email that would match
        _make_raw_email(
            db, email_account,
            gemini_company="Acme Corp",
        )

        # POST capture with same source_url — should hit idempotent path
        resp = client.post(
            "/extension/capture",
            json={
                "company_name": "Acme Corp",
                "role": "Software Engineer",
                "source_url": "https://acme.wd5.myworkdayjobs.com/job/Engineer_R1234567",
                "job_description": "A job description.",
            },
            headers=auth_headers,
        )

        assert resp.status_code == 201
        assert resp.json()["message"] == "existing"

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS
