"""Integration tests for the Gmail polling worker (chunk 10)."""
import uuid
from datetime import datetime, timezone
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
