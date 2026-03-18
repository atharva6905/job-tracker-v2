import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.interview import Interview, RoundType
from app.models.job_description import JobDescription
from app.models.raw_email import RawEmail
from app.utils.encryption import encrypt_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_company(db: Session, user_id: uuid.UUID) -> Company:
    company = Company(
        user_id=user_id,
        name="Acme Corp",
        normalized_name="acme corp",
    )
    db.add(company)
    db.flush()
    return company


def _make_application(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> Application:
    app = Application(
        user_id=user_id,
        company_id=company_id,
        role="Engineer",
        status=ApplicationStatus.APPLIED,
    )
    db.add(app)
    db.flush()
    return app


def _make_email_account(db: Session, user_id: uuid.UUID) -> EmailAccount:
    account = EmailAccount(
        user_id=user_id,
        email="test@gmail.com",
        access_token=encrypt_token("access"),
        refresh_token=encrypt_token("refresh"),
    )
    db.add(account)
    db.flush()
    return account


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_export_returns_200_with_correct_structure(client, auth_headers):
    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "user" in data
    assert "companies" in data
    assert "applications" in data
    assert "interviews" in data
    assert "email_accounts" in data
    assert "raw_emails" in data


def test_export_empty_user_returns_empty_lists(client, auth_headers, test_user):
    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["user"]["id"] == str(test_user.id)
    assert data["companies"] == []
    assert data["applications"] == []
    assert data["interviews"] == []
    assert data["email_accounts"] == []
    assert data["raw_emails"] == []


def test_export_includes_all_created_data(client, auth_headers, test_user, db: Session):
    company = _make_company(db, test_user.id)
    application = _make_application(db, test_user.id, company.id)

    jd = JobDescription(application_id=application.id, raw_text="Job description text")
    db.add(jd)

    interview = Interview(application_id=application.id, round_type=RoundType.PHONE)
    db.add(interview)

    account = _make_email_account(db, test_user.id)

    raw_email = RawEmail(
        email_account_id=account.id,
        gmail_message_id="msg_001",
        linked_application_id=application.id,
    )
    db.add(raw_email)
    db.flush()

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert data["user"]["id"] == str(test_user.id)

    assert len(data["companies"]) == 1
    assert data["companies"][0]["name"] == "Acme Corp"

    assert len(data["applications"]) == 1
    assert data["applications"][0]["role"] == "Engineer"
    assert data["applications"][0]["job_description"]["raw_text"] == "Job description text"

    assert len(data["interviews"]) == 1
    assert data["interviews"][0]["round_type"] == "PHONE"

    assert len(data["email_accounts"]) == 1
    assert data["email_accounts"][0]["email"] == "test@gmail.com"

    assert len(data["raw_emails"]) == 1
    assert data["raw_emails"][0]["gmail_message_id"] == "msg_001"
    assert data["raw_emails"][0]["linked_application_id"] == str(application.id)


def test_export_no_tokens_in_response(client, auth_headers, test_user, db: Session):
    """access_token and refresh_token must never appear anywhere in the export response."""
    _make_email_account(db, test_user.id)

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200

    response_text = resp.text
    assert "access_token" not in response_text
    assert "refresh_token" not in response_text


def test_export_includes_unlinked_raw_emails(
    client, auth_headers, test_user, db: Session
):
    """Raw emails with linked_application_id=NULL must still appear in the export."""
    account = _make_email_account(db, test_user.id)

    raw_email = RawEmail(
        email_account_id=account.id,
        gmail_message_id="msg_unlinked",
        linked_application_id=None,
    )
    db.add(raw_email)
    db.flush()

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["raw_emails"]) == 1
    assert data["raw_emails"][0]["gmail_message_id"] == "msg_unlinked"
    assert data["raw_emails"][0]["linked_application_id"] is None


def test_export_application_without_job_description(
    client, auth_headers, test_user, db: Session
):
    """Application with no job_description should have job_description=null."""
    company = _make_company(db, test_user.id)
    _make_application(db, test_user.id, company.id)

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert len(data["applications"]) == 1
    assert data["applications"][0]["job_description"] is None


def test_export_after_delete_returns_401(client, auth_headers):
    """After DELETE /users/me, the export endpoint returns 401."""
    with patch("app.routers.auth.scheduler"):
        del_resp = client.delete("/users/me", headers=auth_headers)
    assert del_resp.status_code == 204

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 401


def test_export_unauthenticated_returns_401(client):
    resp = client.get("/users/me/export")
    assert resp.status_code == 401
