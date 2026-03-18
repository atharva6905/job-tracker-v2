"""
Verify that DELETE /users/me cascades correctly through all child tables.

Row creation order follows FK dependencies:
  users → companies → applications → (interviews, job_descriptions)
  users → email_accounts → raw_emails (also linked to applications via SET NULL)
"""
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.interview import Interview, RoundType
from app.models.job_description import JobDescription
from app.models.raw_email import RawEmail
from app.models.user import User
from app.utils.encryption import encrypt_token


def test_delete_user_cascades_all_tables(
    client, auth_headers, test_user, db: Session
):
    """
    Create one row in every child table, DELETE /users/me, then assert every
    row is gone via direct DB queries.  Also verifies 204 response code.
    """
    # Company
    company = Company(
        user_id=test_user.id,
        name="DeleteMe Corp",
        normalized_name="deleteme corp",
    )
    db.add(company)
    db.flush()

    # Application
    application = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Test Role",
        status=ApplicationStatus.APPLIED,
    )
    db.add(application)
    db.flush()

    # JobDescription (1-to-1 with application)
    jd = JobDescription(application_id=application.id, raw_text="Some JD")
    db.add(jd)

    # Interview
    interview = Interview(
        application_id=application.id, round_type=RoundType.PHONE
    )
    db.add(interview)

    # EmailAccount
    account = EmailAccount(
        user_id=test_user.id,
        email="delete@gmail.com",
        access_token=encrypt_token("access"),
        refresh_token=encrypt_token("refresh"),
    )
    db.add(account)
    db.flush()

    # RawEmail (linked to both account and application)
    raw_email = RawEmail(
        email_account_id=account.id,
        gmail_message_id="msg_cascade_001",
        linked_application_id=application.id,
    )
    db.add(raw_email)
    db.flush()

    # Capture IDs before deletion
    user_id = test_user.id
    company_id = company.id
    app_id = application.id
    jd_id = jd.id
    interview_id = interview.id
    account_id = account.id
    raw_email_id = raw_email.id

    with patch("app.routers.auth.scheduler"):
        resp = client.delete("/users/me", headers=auth_headers)
    assert resp.status_code == 204

    # Every row must be gone
    assert db.scalar(select(User).where(User.id == user_id)) is None
    assert db.scalar(select(Company).where(Company.id == company_id)) is None
    assert db.scalar(select(Application).where(Application.id == app_id)) is None
    assert db.scalar(select(JobDescription).where(JobDescription.id == jd_id)) is None
    assert (
        db.scalar(select(Interview).where(Interview.id == interview_id)) is None
    )
    assert (
        db.scalar(select(EmailAccount).where(EmailAccount.id == account_id)) is None
    )
    assert (
        db.scalar(select(RawEmail).where(RawEmail.id == raw_email_id)) is None
    )
