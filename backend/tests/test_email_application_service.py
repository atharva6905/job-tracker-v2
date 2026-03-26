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


class TestProcessEmailSignal:
    def test_applied_signal_on_in_progress_is_skipped(self, db, test_user, email_account):
        """IN_PROGRESS + APPLIED signal → skipped (extension handles this transition)."""
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
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert app.date_applied is None
        assert raw_email.linked_application_id is None

    def test_applied_signal_on_in_progress_skipped_even_with_source_url(self, db, test_user, email_account):
        """APPLIED signal on IN_PROGRESS apps is always skipped, regardless of source_url dedup."""
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
        assert app_with_url.status == ApplicationStatus.IN_PROGRESS
        assert app_no_url.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

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

    def test_company_normalization_google_llc_applied_skip(self, db, test_user, email_account):
        """'Google LLC' normalizes to 'google' — match found but APPLIED signal on IN_PROGRESS is skipped."""
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

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

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

    def test_applied_signal_on_in_progress_does_not_set_date_applied(self, db, test_user, email_account):
        """APPLIED email signal on IN_PROGRESS is skipped — date_applied stays None."""
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
        assert app.date_applied is None
        assert app.status == ApplicationStatus.IN_PROGRESS

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

    def test_ats_job_id_match_applied_signal_skipped(
        self, db, test_user, email_account
    ):
        """ATS job ID match finds app but APPLIED signal on IN_PROGRESS is skipped."""
        acme = _make_company(db, test_user.id, name="Acme Corp")
        app_with_id = _make_application(
            db, test_user.id, acme.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Cashier_R2000648316",
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Cashier_R2000648316",
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
        assert app_with_id.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_ats_job_id_falls_through_applied_signal_skipped(
        self, db, test_user, email_account
    ):
        """No R-number in subject → company match found but APPLIED signal on IN_PROGRESS skipped."""
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
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_ats_job_id_no_match_company_fallback_applied_skipped(
        self, db, test_user, email_account
    ):
        """R-number doesn't match → company fallback finds app but APPLIED on IN_PROGRESS skipped."""
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
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_null_company_with_r_number_applied_skipped(
        self, db, test_user, email_account
    ):
        """Gemini returns company=None + R-number → match found but APPLIED on IN_PROGRESS skipped."""
        company = _make_company(db, test_user.id, name="Sdm Careers")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            ats_job_id="Merchandiser_R2000639673",
            source_url="https://sdm.wd5.myworkdayjobs.com/en-US/sdm_careers/job/Merchandiser_R2000639673",
        )

        raw_email = _make_raw_email(
            db, email_account,
            subject="Follow up on your application for R2000639673 Merchandiser (Open)",
        )

        classification = GeminiClassificationResult(
            company=None,
            role="Merchandiser",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_null_company_without_r_number_is_no_op(
        self, db, test_user, email_account
    ):
        """Gemini returns company=None and no R-number in subject → no-op (original behavior)."""
        company = _make_company(db, test_user.id)
        _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
        )

        raw_email = _make_raw_email(
            db, email_account, subject="Thanks for applying!",
        )

        classification = GeminiClassificationResult(
            company=None,
            role="Engineer",
            signal="APPLIED",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        assert raw_email.linked_application_id is None


class TestWorkdayTenantMatching:
    """Tests for Priority 1: Workday tenant deduplication."""

    def test_tenant_match_applied_signal_skipped(self, db, test_user, email_account):
        """Sender tenant matches but APPLIED signal on IN_PROGRESS is skipped."""
        company = _make_company(db, test_user.id, "Meredith")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "meredith@myworkday.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="People Inc.",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_shared_sender_applied_signal_skipped(self, db, test_user, email_account):
        """Shared sender falls through to company match, but APPLIED on IN_PROGRESS is skipped."""
        company = _make_company(db, test_user.id, "Acme Corp")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            workday_tenant="acme",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "noreply@myworkday.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Acme Corp",
            role="Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS

    def test_two_apps_same_tenant_applied_signal_skipped(self, db, test_user, email_account):
        """Two apps with same tenant — Jaccard finds match but APPLIED on IN_PROGRESS skipped."""
        company = _make_company(db, test_user.id, "Meredith")
        app1 = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith", role="Software Engineer",
        )
        app2 = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith", role="Data Analyst",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "meredith@myworkday.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="People Inc.",
            role="Data Analyst",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app1)
        db.refresh(app2)
        assert app1.status == ApplicationStatus.IN_PROGRESS
        assert app2.status == ApplicationStatus.IN_PROGRESS

    def test_tenant_match_for_interview_signal(self, db, test_user, email_account):
        """Tenant matching works for non-APPLIED signals (INTERVIEW)."""
        company = _make_company(db, test_user.id, "Meredith")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
            workday_tenant="meredith",
        )

        raw_email = _make_raw_email(
            db, email_account, gemini_signal="INTERVIEW",
        )
        raw_email.sender = "meredith@myworkday.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="People Inc.",
            role="Software Engineer",
            signal="INTERVIEW",
            confidence=0.90,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.INTERVIEW


class TestJaccardSimilarity:
    """Tests for Priority 4: role token Jaccard similarity fallback."""

    def test_jaccard_matches_similar_roles_applied_skipped(self, db, test_user, email_account):
        """Jaccard >= 0.7 finds match but APPLIED signal on IN_PROGRESS is skipped."""
        company = _make_company(db, test_user.id, "Unknown Corp")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Software Engineer Intern",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "careers@example.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Nonexistent Co",
            role="Software Engineer Intern 2026",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS

    def test_jaccard_below_threshold_no_match(self, db, test_user, email_account):
        """Jaccard < 0.7 — no match, no-op."""
        company = _make_company(db, test_user.id, "Unknown Corp")
        _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Data Scientist",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "careers@example.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Nonexistent Co",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        assert raw_email.linked_application_id is None

    def test_jaccard_multiple_matches_no_op(self, db, test_user, email_account):
        """Multiple apps matching via Jaccard — ambiguous, no-op."""
        company = _make_company(db, test_user.id, "Unknown Corp")
        app1 = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Software Engineer",
        )
        app2 = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Software Engineer",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "careers@example.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Nonexistent Co",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app1)
        db.refresh(app2)
        assert app1.status == ApplicationStatus.IN_PROGRESS
        assert app2.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_jaccard_excludes_old_apps(self, db, test_user, email_account):
        """Apps older than 14 days are excluded from Jaccard matching."""
        from datetime import timezone

        company = _make_company(db, test_user.id, "Unknown Corp")
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Software Engineer",
        )
        # Manually backdate the application
        app.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        db.flush()

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "careers@example.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Nonexistent Co",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS
        assert raw_email.linked_application_id is None

    def test_jaccard_null_role_no_match(self, db, test_user, email_account):
        """When classification.role is None, Jaccard doesn't fire."""
        company = _make_company(db, test_user.id, "Unknown Corp")
        _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            role="Software Engineer",
        )

        raw_email = _make_raw_email(db, email_account)
        raw_email.sender = "careers@example.com"
        db.flush()

        classification = GeminiClassificationResult(
            company="Nonexistent Co",
            role=None,
            signal="APPLIED",
            confidence=0.95,
        )

        process_email_signal(db, test_user.id, raw_email, classification)

        assert raw_email.linked_application_id is None


class TestSoftDeleteEmailMatching:
    """Soft-deleted applications must be invisible to email matching."""

    def test_soft_deleted_app_not_matched_by_email(self, db, test_user, email_account):
        """Soft-deleted application is invisible to _find_matching_application."""
        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
        )
        app.deleted_at = datetime(2026, 3, 20, tzinfo=timezone.utc)
        db.flush()

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
        assert app.status == ApplicationStatus.APPLIED  # unchanged
        assert raw_email.linked_application_id is None


class TestReplaySignalFiltering:
    """replay_matched_emails must skip APPLIED signals."""

    def test_replay_skips_applied_signal(self, db, test_user, email_account):
        """APPLIED emails in raw_emails are not replayed."""
        from app.services.email_application_service import replay_matched_emails

        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.IN_PROGRESS,
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Eng_R123",
        )

        # Create an unlinked APPLIED email matching the company
        raw_email = _make_raw_email(
            db, email_account,
            gemini_signal="APPLIED", gemini_confidence=0.95,
        )
        raw_email.gemini_company = "Acme Corp"
        db.flush()

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.IN_PROGRESS  # NOT advanced to APPLIED

    def test_replay_still_replays_interview(self, db, test_user, email_account):
        """INTERVIEW signal is still replayed correctly."""
        from app.services.email_application_service import replay_matched_emails

        company = _make_company(db, test_user.id)
        app = _make_application(
            db, test_user.id, company.id, ApplicationStatus.APPLIED,
            source_url="https://acme.wd5.myworkdayjobs.com/en-US/careers/job/Eng_R123",
        )

        raw_email = _make_raw_email(
            db, email_account,
            gemini_signal="INTERVIEW", gemini_confidence=0.90,
        )
        raw_email.gemini_company = "Acme Corp"
        db.flush()

        replay_matched_emails(db, app)

        db.refresh(app)
        assert app.status == ApplicationStatus.INTERVIEW
        assert raw_email.linked_application_id == app.id
