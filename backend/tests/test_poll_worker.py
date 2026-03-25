"""Integration tests for the Gmail polling worker (chunk 10)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.models.user import User
from app.services.gemini_service import GeminiClassificationResult
from app.utils.encryption import encrypt_token
from app.utils.gmail_client import GmailClientInterface, MockGmailClient

_MOCK_CLASSIFICATION = GeminiClassificationResult(
    company="Test Company",
    role="Software Engineer",
    signal="APPLIED",
    confidence=0.95,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(db: Session, user: User, **kwargs) -> EmailAccount:
    account = EmailAccount(
        id=uuid.uuid4(),
        user_id=user.id,
        email="poll@gmail.com",
        access_token=encrypt_token("fake_access"),
        refresh_token=encrypt_token("fake_refresh"),
        **kwargs,
    )
    db.add(account)
    db.flush()
    return account


def _ats_message(msg_id: str, snippet: str = "We received your application.") -> dict:
    """A message that passes the pre-filter via ATS sender domain."""
    return {
        "id": msg_id,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Application received — Software Engineer"},
                {"name": "From", "value": "no-reply@greenhouse.io"},
                {"name": "Date", "value": "Thu, 18 Mar 2026 10:00:00 +0000"},
            ]
        },
    }


def _noise_message(msg_id: str) -> dict:
    """A message that fails the pre-filter (not ATS, no job keywords)."""
    return {
        "id": msg_id,
        "snippet": "Your Amazon order has shipped.",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your order has shipped"},
                {"name": "From", "value": "no-reply@amazon.com"},
                {"name": "Date", "value": "Thu, 18 Mar 2026 10:00:00 +0000"},
            ]
        },
    }


def _run_poll(db: Session, account_id: str, gmail_client: GmailClientInterface) -> None:
    """Patch SessionLocal so poll_gmail_account uses the test transaction.

    Also mocks classify_email (returns a fixed APPLIED result) and
    process_email_signal (no-op) so poll worker tests stay focused on
    polling logic without hitting the real Gemini API or triggering
    application side-effects.
    """
    from app.jobs.poll_job import poll_gmail_account

    wrapped = MagicMock(wraps=db)
    wrapped.close = MagicMock()
    with (
        patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
        patch("app.jobs.poll_job.classify_email", return_value=_MOCK_CLASSIFICATION),
        patch("app.jobs.poll_job.process_email_signal"),
        patch(
            "app.jobs.poll_job._load_active_company_names",
            return_value={"test company"},
        ),
        patch(
            "app.jobs.poll_job._load_active_workday_tenants",
            return_value=set(),
        ),
    ):
        poll_gmail_account(account_id, gmail_client=gmail_client)
    wrapped.close.assert_called_once()


# ---------------------------------------------------------------------------
# Paginated mock client
# ---------------------------------------------------------------------------

class _PaginatedMockClient(GmailClientInterface):
    """Returns messages across two pages; second page has no nextPageToken."""

    def __init__(self, page1: list, page2: list):
        self._page1 = page1
        self._page2 = page2

    def get_messages_since(self, account_id, since_timestamp, page_token=None):
        if page_token is None:
            return {
                "messages": [{"id": m["id"]} for m in self._page1],
                "nextPageToken": "page2",
            }
        return {"messages": [{"id": m["id"]} for m in self._page2]}

    def get_message_detail(self, message_id):
        for m in self._page1 + self._page2:
            if m["id"] == message_id:
                return m
        raise ValueError(f"Message {message_id} not found in mock")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPollGmailAccount:
    def test_empty_inbox_updates_last_polled_at(self, db, test_user):
        """With no messages, last_polled_at is set and no raw_emails are created."""
        account = _make_account(db, test_user)

        _run_poll(db, str(account.id), MockGmailClient(messages=[]))

        assert account.last_polled_at is not None
        count = db.scalar(
            select(func.count(RawEmail.id)).where(
                RawEmail.email_account_id == account.id
            )
        )
        assert count == 0

    def test_ats_sender_stores_raw_email(self, db, test_user):
        """An email from a known ATS domain is stored with correct field values."""
        account = _make_account(db, test_user)
        msg = _ats_message("msg_ats_001")
        _run_poll(db, str(account.id), MockGmailClient(messages=[msg]))

        rows = db.scalars(
            select(RawEmail).where(RawEmail.email_account_id == account.id)
        ).all()
        assert len(rows) == 1

        row = rows[0]
        assert row.gmail_message_id == "msg_ats_001"
        assert row.email_account_id == account.id
        assert row.subject == "Application received — Software Engineer"
        assert "greenhouse.io" in row.sender
        assert row.received_at is not None
        assert row.gemini_signal == "APPLIED"
        assert row.gemini_confidence == 0.95

    def test_body_snippet_truncated_to_500_chars(self, db, test_user):
        """body_snippet is never longer than 500 characters regardless of input length."""
        long_snippet = "x" * 600
        account = _make_account(db, test_user)
        msg = _ats_message("msg_long_001", snippet=long_snippet)
        _run_poll(db, str(account.id), MockGmailClient(messages=[msg]))

        row = db.scalar(
            select(RawEmail).where(RawEmail.gmail_message_id == "msg_long_001")
        )
        assert row is not None
        assert len(row.body_snippet) == 500

    def test_non_job_email_not_stored(self, db, test_user):
        """An email that fails the pre-filter is not written to raw_emails."""
        account = _make_account(db, test_user)
        _run_poll(db, str(account.id), MockGmailClient(messages=[_noise_message("msg_noise_001")]))

        count = db.scalar(
            select(func.count(RawEmail.id)).where(
                RawEmail.email_account_id == account.id
            )
        )
        assert count == 0

    def test_dedup_skip_no_duplicate_created(self, db, test_user):
        """A message whose gmail_message_id is already in raw_emails is not duplicated."""
        account = _make_account(db, test_user)

        # Pre-seed a raw_email row with the same gmail_message_id
        existing = RawEmail(
            email_account_id=account.id,
            gmail_message_id="msg_dup_001",
            subject="Already stored",
            sender="no-reply@greenhouse.io",
            received_at=datetime.now(timezone.utc),
            body_snippet="existing snippet",
        )
        db.add(existing)
        db.flush()

        _run_poll(
            db,
            str(account.id),
            MockGmailClient(messages=[_ats_message("msg_dup_001")]),
        )

        count = db.scalar(
            select(func.count(RawEmail.id)).where(
                RawEmail.email_account_id == account.id
            )
        )
        assert count == 1  # still exactly one row — no duplicate

    def test_paginated_results_all_pages_processed(self, db, test_user):
        """All messages across multiple pages are processed and stored."""
        account = _make_account(db, test_user)
        page1 = [_ats_message("msg_p1_001"), _ats_message("msg_p1_002")]
        page2 = [_ats_message("msg_p2_001")]

        _run_poll(db, str(account.id), _PaginatedMockClient(page1, page2))

        stored_ids = {
            r.gmail_message_id
            for r in db.scalars(
                select(RawEmail).where(RawEmail.email_account_id == account.id)
            ).all()
        }
        assert stored_ids == {"msg_p1_001", "msg_p1_002", "msg_p2_001"}

    def test_mixed_inbox_only_job_emails_stored(self, db, test_user):
        """Only job-related emails pass the pre-filter; noise is discarded."""
        account = _make_account(db, test_user)
        messages = [
            _ats_message("msg_job_001"),
            _noise_message("msg_noise_001"),
            _ats_message("msg_job_002"),
        ]
        _run_poll(db, str(account.id), MockGmailClient(messages=messages))

        stored_ids = {
            r.gmail_message_id
            for r in db.scalars(
                select(RawEmail).where(RawEmail.email_account_id == account.id)
            ).all()
        }
        assert stored_ids == {"msg_job_001", "msg_job_002"}
        assert "msg_noise_001" not in stored_ids

    def test_unknown_account_id_returns_gracefully(self, db):
        """poll_gmail_account logs a warning and returns when account is not found."""
        _run_poll(db, str(uuid.uuid4()), MockGmailClient(messages=[]))
        # No exception raised — the job silently skips the unknown account


class TestInProgressGate:
    """Tests for the two-level gate that skips emails without matching active applications."""

    def test_no_active_apps_skips_gemini(self, db, test_user):
        """A1/B1: When the user has no active applications, Gemini is never called."""
        account = _make_account(db, test_user)
        msg = _ats_message("msg_gate_001")

        from app.jobs.poll_job import poll_gmail_account

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()
        mock_classify = MagicMock()

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", mock_classify),
            patch("app.jobs.poll_job.process_email_signal"),
            # _load_active_company_names returns the real result: empty set (no apps)
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        mock_classify.assert_not_called()
        wrapped.close.assert_called_once()

    def test_matching_company_stores_and_triggers_transition(self, db, test_user):
        """B2/C2: Email whose company matches an active app is stored and transitioned."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        # Create an IN_PROGRESS application for "Test Company" (matches _MOCK_CLASSIFICATION.company)
        company = Company(
            user_id=test_user.id,
            name="Test Company",
            normalized_name=normalize_company_name("Test Company"),
        )
        db.add(company)
        db.flush()
        app = Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Software Engineer",
            status=ApplicationStatus.IN_PROGRESS,
        )
        db.add(app)
        db.flush()

        msg = _ats_message("msg_gate_002")
        mock_process = MagicMock()

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=_MOCK_CLASSIFICATION),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        # Email stored in raw_emails
        from sqlalchemy import select
        from app.models.raw_email import RawEmail
        row = db.scalar(select(RawEmail).where(RawEmail.gmail_message_id == "msg_gate_002"))
        assert row is not None
        assert row.gemini_signal == "APPLIED"
        # Transition was triggered
        mock_process.assert_called_once()
        wrapped.close.assert_called_once()

    def test_non_matching_company_not_stored(self, db, test_user):
        """C1: Email whose company has no matching active app is dropped — not stored."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        # Active app for "Acme Corp" — does NOT match "Test Company" from _MOCK_CLASSIFICATION
        company = Company(
            user_id=test_user.id,
            name="Acme Corp",
            normalized_name=normalize_company_name("Acme Corp"),
        )
        db.add(company)
        db.flush()
        db.add(Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.IN_PROGRESS,
        ))
        db.flush()

        msg = _ats_message("msg_gate_003")
        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account
        from sqlalchemy import select
        from app.models.raw_email import RawEmail

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=_MOCK_CLASSIFICATION),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        row = db.scalar(select(RawEmail).where(RawEmail.gmail_message_id == "msg_gate_003"))
        assert row is None  # fine gate dropped it
        mock_process.assert_not_called()  # fine gate prevented process_email_signal
        wrapped.close.assert_called_once()

    def test_null_company_from_gemini_not_stored(self, db, test_user):
        """C3: APPLIED signal with no company extracted → dropped by fine gate."""
        account = _make_account(db, test_user)
        msg = _ats_message("msg_gate_004")

        null_company_classification = GeminiClassificationResult(
            company=None,
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account
        from sqlalchemy import select
        from app.models.raw_email import RawEmail

        mock_process = MagicMock()
        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=null_company_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"test company"},
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        row = db.scalar(select(RawEmail).where(RawEmail.gmail_message_id == "msg_gate_004"))
        assert row is None
        mock_process.assert_not_called()  # fine gate prevented process_email_signal
        wrapped.close.assert_called_once()

    def test_parse_error_stored_when_active_apps_exist(self, db, test_user):
        """D1: PARSE_ERROR + active apps present → email stored (can't gate by company)."""
        account = _make_account(db, test_user)
        msg = _ats_message("msg_gate_005")

        parse_error_classification = GeminiClassificationResult(
            company=None,
            role=None,
            signal="PARSE_ERROR",
            confidence=0.0,
        )

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account
        from sqlalchemy import select
        from app.models.raw_email import RawEmail

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=parse_error_classification),
            patch("app.jobs.poll_job.process_email_signal"),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"test company"},
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        row = db.scalar(select(RawEmail).where(RawEmail.gmail_message_id == "msg_gate_005"))
        assert row is not None
        assert row.gemini_signal == "PARSE_ERROR"
        wrapped.close.assert_called_once()

    def test_active_company_set_excludes_terminal_states(self, db, test_user):
        """A2: OFFER and REJECTED apps are excluded from the active company set."""
        from app.jobs.poll_job import _load_active_company_names
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        # Create companies and apps in all statuses
        # Note: names chosen to avoid legal suffix stripping (e.g. "Corp" is stripped)
        statuses = [
            ("Acme Active", ApplicationStatus.IN_PROGRESS),
            ("Acme Applied", ApplicationStatus.APPLIED),
            ("Acme Interview", ApplicationStatus.INTERVIEW),
            ("Acme Offer", ApplicationStatus.OFFER),
            ("Acme Rejected", ApplicationStatus.REJECTED),
        ]
        for name, status in statuses:
            company = Company(
                user_id=test_user.id,
                name=name,
                normalized_name=normalize_company_name(name),
            )
            db.add(company)
            db.flush()
            db.add(Application(
                user_id=test_user.id,
                company_id=company.id,
                role="Engineer",
                status=status,
            ))
        db.flush()

        result = _load_active_company_names(db, test_user.id)

        assert "acme active" in result
        assert "acme applied" in result
        assert "acme interview" in result
        assert "acme offer" not in result      # terminal — excluded
        assert "acme rejected" not in result   # terminal — excluded

    def test_parse_error_retry_matching_company_triggers_transition(self, db, test_user):
        """F1: PARSE_ERROR retry — company now extracted and in active set → process_email_signal called."""
        from app.models.raw_email import RawEmail
        from datetime import datetime, timezone

        account = _make_account(db, test_user)

        # Pre-seed a stored PARSE_ERROR email (from a previous failed poll cycle)
        existing = RawEmail(
            email_account_id=account.id,
            gmail_message_id="msg_retry_f1",
            subject="Application Update",
            sender="no-reply@greenhouse.io",
            received_at=datetime.now(timezone.utc),
            body_snippet="We wanted to follow up...",
            gemini_signal="PARSE_ERROR",
            gemini_confidence=0.0,
        )
        db.add(existing)
        db.flush()

        # Retry re-classification returns a company that IS in active_companies
        retry_classification = GeminiClassificationResult(
            company="Test Company",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.90,
        )

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            # Empty inbox — only retry loop fires, not main loop
            patch("app.jobs.poll_job.classify_email", return_value=retry_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"test company"},
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[]))

        # Retry loop should have called process_email_signal
        mock_process.assert_called_once()
        wrapped.close.assert_called_once()

    def test_parse_error_retry_non_matching_company_no_transition(self, db, test_user):
        """F2: PARSE_ERROR retry — company extracted but NOT in active set → no transition."""
        from app.models.raw_email import RawEmail
        from datetime import datetime, timezone

        account = _make_account(db, test_user)

        # Pre-seed a stored PARSE_ERROR email
        existing = RawEmail(
            email_account_id=account.id,
            gmail_message_id="msg_retry_f2",
            subject="Application Update",
            sender="no-reply@greenhouse.io",
            received_at=datetime.now(timezone.utc),
            body_snippet="We wanted to follow up...",
            gemini_signal="PARSE_ERROR",
            gemini_confidence=0.0,
        )
        db.add(existing)
        db.flush()

        # Retry re-classification returns a company NOT in active_companies
        retry_classification = GeminiClassificationResult(
            company="Unknown Corp",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.90,
        )

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=retry_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"test company"},  # "unknown corp" not in this set
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[]))

        # process_email_signal should NOT be called — company didn't match
        mock_process.assert_not_called()
        wrapped.close.assert_called_once()


# ---------------------------------------------------------------------------
# PARSE_ERROR cleanup
# ---------------------------------------------------------------------------

class TestParseErrorCleanup:
    """Orphaned PARSE_ERROR rows older than 30 days are purged at end of poll."""

    def test_deletes_old_orphaned_parse_errors(self, db: Session, test_user: User):
        account = _make_account(db, test_user)

        old_date = datetime.now(timezone.utc) - timedelta(days=45)
        recent_date = datetime.now(timezone.utc) - timedelta(days=5)

        # Old orphan — should be deleted
        old_orphan = RawEmail(
            id=uuid.uuid4(),
            email_account_id=account.id,
            gmail_message_id="old_orphan_1",
            subject="s",
            sender="s@ats.com",
            received_at=old_date,
            body_snippet="",
            gemini_signal="PARSE_ERROR",
            linked_application_id=None,
        )
        # Recent orphan — should survive (< 30 days old)
        recent_orphan = RawEmail(
            id=uuid.uuid4(),
            email_account_id=account.id,
            gmail_message_id="recent_orphan_1",
            subject="s",
            sender="s@ats.com",
            received_at=recent_date,
            body_snippet="",
            gemini_signal="PARSE_ERROR",
            linked_application_id=None,
        )
        # Old but linked — should survive (has linked_application_id)
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company

        company = Company(
            id=uuid.uuid4(),
            user_id=test_user.id,
            name="Acme",
            normalized_name="acme",
        )
        db.add(company)
        db.flush()
        app = Application(
            id=uuid.uuid4(),
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.IN_PROGRESS,
        )
        db.add(app)
        db.flush()

        old_linked = RawEmail(
            id=uuid.uuid4(),
            email_account_id=account.id,
            gmail_message_id="old_linked_1",
            subject="s",
            sender="s@ats.com",
            received_at=old_date,
            body_snippet="",
            gemini_signal="PARSE_ERROR",
            linked_application_id=app.id,
        )
        # Old non-PARSE_ERROR — should survive (different signal)
        old_applied = RawEmail(
            id=uuid.uuid4(),
            email_account_id=account.id,
            gmail_message_id="old_applied_1",
            subject="s",
            sender="s@ats.com",
            received_at=old_date,
            body_snippet="",
            gemini_signal="APPLIED",
            gemini_confidence=0.95,
            linked_application_id=None,
        )

        db.add_all([old_orphan, recent_orphan, old_linked, old_applied])
        db.flush()

        # Mock classify_email to keep PARSE_ERROR signal — so the retry loop
        # doesn't change signals before cleanup runs.
        still_broken = GeminiClassificationResult(
            company=None, role=None, signal="PARSE_ERROR", confidence=0.0,
        )

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job._load_active_company_names", return_value={"acme"}),
            patch("app.jobs.poll_job.classify_email", return_value=still_broken),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[]))

        remaining_ids = set(
            db.scalars(
                select(RawEmail.gmail_message_id).where(
                    RawEmail.email_account_id == account.id,
                )
            ).all()
        )
        assert "old_orphan_1" not in remaining_ids
        assert "recent_orphan_1" in remaining_ids
        assert "old_linked_1" in remaining_ids
        assert "old_applied_1" in remaining_ids


# ---------------------------------------------------------------------------
# Workday tenant fine gate bypass
# ---------------------------------------------------------------------------


class TestTenantFineGate:
    """Tests for tenant-based fine gate bypass."""

    def test_fine_gate_passes_on_tenant_match(self, db, test_user):
        """Email from tenant@myworkday.com passes fine gate when tenant matches active app,
        even when Gemini company name doesn't match any active company."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        # Active app with workday_tenant="meredith" but company is "Meredith"
        company = Company(
            user_id=test_user.id,
            name="Meredith",
            normalized_name=normalize_company_name("Meredith"),
        )
        db.add(company)
        db.flush()
        db.add(Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith",
        ))
        db.flush()

        # Email sender is meredith@myworkday.com, but Gemini says company is "People Inc."
        tenant_classification = GeminiClassificationResult(
            company="People Inc.",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.95,
        )

        msg = {
            "id": "msg_tenant_001",
            "snippet": "Thank you for applying...",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Application received — Software Engineer"},
                    {"name": "From", "value": "meredith@myworkday.com"},
                    {"name": "Date", "value": "Thu, 18 Mar 2026 10:00:00 +0000"},
                ]
            },
        }

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account
        from sqlalchemy import select as sa_select
        from app.models.raw_email import RawEmail

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=tenant_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch("app.jobs.poll_job.is_job_related", return_value=True),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        # Email should be stored (fine gate bypassed via tenant)
        row = db.scalar(sa_select(RawEmail).where(RawEmail.gmail_message_id == "msg_tenant_001"))
        assert row is not None
        assert row.gemini_signal == "APPLIED"
        mock_process.assert_called_once()
        wrapped.close.assert_called_once()

    def test_parse_error_retry_with_tenant_match(self, db, test_user):
        """PARSE_ERROR retry: sender tenant matches active tenant → process_email_signal called."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.models.raw_email import RawEmail
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        # Active app with workday_tenant
        company = Company(
            user_id=test_user.id,
            name="Meredith",
            normalized_name=normalize_company_name("Meredith"),
        )
        db.add(company)
        db.flush()
        db.add(Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.IN_PROGRESS,
            workday_tenant="meredith",
        ))
        db.flush()

        # Pre-seed a PARSE_ERROR email from a Workday tenant sender
        existing = RawEmail(
            email_account_id=account.id,
            gmail_message_id="msg_retry_tenant_1",
            subject="Application Update",
            sender="meredith@myworkday.com",
            received_at=datetime.now(timezone.utc),
            body_snippet="We wanted to follow up...",
            gemini_signal="PARSE_ERROR",
            gemini_confidence=0.0,
        )
        db.add(existing)
        db.flush()

        # Retry classification: company doesn't match active companies, but tenant does
        retry_classification = GeminiClassificationResult(
            company="People Inc.",
            role="Software Engineer",
            signal="APPLIED",
            confidence=0.90,
        )

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=retry_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"meredith"},  # "people inc." not in this set
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[]))

        # Retry loop should fire process_email_signal via tenant bypass
        mock_process.assert_called_once()
        wrapped.close.assert_called_once()


# ---------------------------------------------------------------------------
# R-number fine gate bypass
# ---------------------------------------------------------------------------


class TestRNumberFineGate:
    """Tests for R-number (ats_job_id) fine gate bypass in the poll worker."""

    def test_fine_gate_passes_on_r_number_match(self, db, test_user):
        """Email with R-number in subject bypasses fine gate even when company doesn't match."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        # Active app with ats_job_id containing an R-number
        company = Company(
            user_id=test_user.id,
            name="Acme Corp",
            normalized_name=normalize_company_name("Acme Corp"),
        )
        db.add(company)
        db.flush()
        db.add(Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.APPLIED,
            ats_job_id="R2000648316",
        ))
        db.flush()

        # Gemini returns a company that is NOT in active_companies
        r_number_classification = GeminiClassificationResult(
            company="Unknown HR Platform",
            role="Software Engineer",
            signal="INTERVIEW",
            confidence=0.92,
        )

        msg = {
            "id": "msg_rnumber_001",
            "snippet": "Interview scheduled...",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Interview for R2000648316 — Software Engineer"},
                    {"name": "From", "value": "no-reply@greenhouse.io"},
                    {"name": "Date", "value": "Thu, 18 Mar 2026 10:00:00 +0000"},
                ]
            },
        }

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=r_number_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"acme"},  # "unknown hr platform" is NOT in this set
            ),
            patch(
                "app.jobs.poll_job._load_active_workday_tenants",
                return_value=set(),
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[msg]))

        # Email should be stored and process_email_signal called (fine gate bypassed via R-number)
        row = db.scalar(select(RawEmail).where(RawEmail.gmail_message_id == "msg_rnumber_001"))
        assert row is not None
        assert row.gemini_signal == "INTERVIEW"
        mock_process.assert_called_once()
        wrapped.close.assert_called_once()

    def test_parse_error_retry_with_r_number_match(self, db, test_user):
        """PARSE_ERROR retry: R-number in subject matches active app → process_email_signal called."""
        from app.models.application import Application, ApplicationStatus
        from app.models.company import Company
        from app.utils.company import normalize_company_name

        account = _make_account(db, test_user)

        company = Company(
            user_id=test_user.id,
            name="Acme Corp",
            normalized_name=normalize_company_name("Acme Corp"),
        )
        db.add(company)
        db.flush()
        db.add(Application(
            user_id=test_user.id,
            company_id=company.id,
            role="Engineer",
            status=ApplicationStatus.IN_PROGRESS,
            ats_job_id="R2000648316",
        ))
        db.flush()

        # Pre-seed a PARSE_ERROR email whose subject contains the R-number
        existing = RawEmail(
            email_account_id=account.id,
            gmail_message_id="msg_retry_rnum_1",
            subject="Update for R2000648316",
            sender="no-reply@greenhouse.io",
            received_at=datetime.now(timezone.utc),
            body_snippet="We wanted to follow up...",
            gemini_signal="PARSE_ERROR",
            gemini_confidence=0.0,
        )
        db.add(existing)
        db.flush()

        retry_classification = GeminiClassificationResult(
            company="Unknown HR",
            role="Software Engineer",
            signal="INTERVIEW",
            confidence=0.90,
        )

        mock_process = MagicMock()
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch("app.jobs.poll_job.classify_email", return_value=retry_classification),
            patch("app.jobs.poll_job.process_email_signal", mock_process),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"acme"},  # "unknown hr" not in this set
            ),
            patch(
                "app.jobs.poll_job._load_active_workday_tenants",
                return_value=set(),
            ),
        ):
            poll_gmail_account(str(account.id), gmail_client=MockGmailClient(messages=[]))

        mock_process.assert_called_once()
        wrapped.close.assert_called_once()


# ---------------------------------------------------------------------------
# Error client — poll worker handles Gmail API errors gracefully
# ---------------------------------------------------------------------------


class TestGmailClientErrors:
    """Verify the poll worker survives Gmail client errors without crashing."""

    def test_gmail_api_error_logged_not_raised(self, db, test_user):
        """When GmailClient raises, poll_gmail_account logs the error and returns."""
        from app.utils.gmail_client import ErrorGmailClient

        account = _make_account(db, test_user)
        error_client = ErrorGmailClient(Exception("Token has been expired or revoked"))

        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        from app.jobs.poll_job import poll_gmail_account

        with (
            patch("app.jobs.poll_job.SessionLocal", return_value=wrapped),
            patch(
                "app.jobs.poll_job._load_active_company_names",
                return_value={"test company"},
            ),
            patch(
                "app.jobs.poll_job._load_active_workday_tenants",
                return_value=set(),
            ),
        ):
            # Should not raise — error is caught by the top-level except in poll_gmail_account
            poll_gmail_account(str(account.id), gmail_client=error_client)

        wrapped.close.assert_called_once()
