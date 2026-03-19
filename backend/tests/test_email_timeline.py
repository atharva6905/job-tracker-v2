"""Integration tests for GET /applications/{id}/emails (chunk 17)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.models.user import User
from app.utils.encryption import encrypt_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_company(db: Session, test_user: User) -> Company:
    company = Company(
        user_id=test_user.id,
        name="Acme Corp",
        normalized_name="acme",
    )
    db.add(company)
    db.flush()
    return company


@pytest.fixture
def test_application(db: Session, test_user: User, test_company: Company) -> Application:
    app = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Software Engineer",
        status=ApplicationStatus.APPLIED,
    )
    db.add(app)
    db.flush()
    return app


@pytest.fixture
def email_account(db: Session, test_user: User) -> EmailAccount:
    account = EmailAccount(
        user_id=test_user.id,
        email="test@gmail.com",
        access_token=encrypt_token("fake_access"),
        refresh_token=encrypt_token("fake_refresh"),
    )
    db.add(account)
    db.flush()
    return account


def _make_raw_email(
    db: Session,
    account: EmailAccount,
    application: Application,
    *,
    gmail_message_id: str,
    received_at: datetime | None = None,
    gemini_signal: str | None = "APPLIED",
    gemini_confidence: float | None = 0.95,
    subject: str | None = "Application received",
    sender: str | None = "no-reply@greenhouse.io",
    body_snippet: str | None = "Thank you for applying.",
) -> RawEmail:
    email = RawEmail(
        email_account_id=account.id,
        gmail_message_id=gmail_message_id,
        subject=subject,
        sender=sender,
        received_at=received_at,
        body_snippet=body_snippet,
        gemini_signal=gemini_signal,
        gemini_confidence=gemini_confidence,
        linked_application_id=application.id,
    )
    db.add(email)
    db.flush()
    return email


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_get_emails_returns_200_with_correct_emails(
    client, auth_headers, db, test_application, email_account
):
    _make_raw_email(
        db,
        email_account,
        test_application,
        gmail_message_id="msg_001",
        received_at=datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc),
        gemini_signal="APPLIED",
        sender="no-reply@greenhouse.io",
    )
    response = client.get(
        f"/applications/{test_application.id}/emails",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["gemini_signal"] == "APPLIED"
    assert data[0]["sender"] == "no-reply@greenhouse.io"
    assert data[0]["gemini_confidence"] == 0.95


def test_get_emails_non_owned_application_returns_404(
    client, other_auth_headers, db, test_application, email_account
):
    _make_raw_email(
        db,
        email_account,
        test_application,
        gmail_message_id="msg_002",
        received_at=datetime(2026, 3, 18, 10, 0, 0, tzinfo=timezone.utc),
    )
    response = client.get(
        f"/applications/{test_application.id}/emails",
        headers=other_auth_headers,
    )
    assert response.status_code == 404


def test_get_emails_no_linked_emails_returns_empty_array(
    client, auth_headers, test_application
):
    response = client.get(
        f"/applications/{test_application.id}/emails",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


def test_get_emails_ordered_by_received_at_asc(
    client, auth_headers, db, test_application, email_account
):
    base = datetime(2026, 3, 18, tzinfo=timezone.utc)
    _make_raw_email(
        db, email_account, test_application,
        gmail_message_id="msg_c",
        received_at=base + timedelta(hours=2),
    )
    _make_raw_email(
        db, email_account, test_application,
        gmail_message_id="msg_a",
        received_at=base,
    )
    _make_raw_email(
        db, email_account, test_application,
        gmail_message_id="msg_b",
        received_at=base + timedelta(hours=1),
    )
    response = client.get(
        f"/applications/{test_application.id}/emails",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    received_times = [d["received_at"] for d in data]
    assert received_times == sorted(received_times)
