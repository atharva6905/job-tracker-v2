import requests as http_requests

from apscheduler.jobstores.base import JobLookupError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import User, get_current_user, get_or_create_current_user
from app.dependencies.rate_limit import limiter
from app.models.application import Application
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.interview import Interview
from app.models.job_description import JobDescription
from app.models.raw_email import RawEmail
from app.scheduler import scheduler
from app.schemas.user import UserResponse
from app.utils.encryption import decrypt_token
from app.utils.logging import get_logger

router = APIRouter()
_logger = get_logger("auth")


@router.get("/auth/me", response_model=UserResponse)
@limiter.limit("60/minute")
def get_me(request: Request, current_user: User = Depends(get_or_create_current_user)) -> User:
    _logger.debug("Auth successful", extra={"user_id": str(current_user.id)})
    return current_user


@router.get("/users/me/export")
@limiter.limit("5/hour")
def export_user_data(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    companies = db.scalars(
        select(Company).where(Company.user_id == current_user.id)
    ).all()

    applications = db.scalars(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    ).all()

    app_ids = [a.id for a in applications]

    jd_by_app: dict = {}
    interviews: list = []
    if app_ids:
        for jd in db.scalars(
            select(JobDescription).where(JobDescription.application_id.in_(app_ids))
        ).all():
            jd_by_app[jd.application_id] = jd
        interviews = db.scalars(
            select(Interview).where(Interview.application_id.in_(app_ids))
        ).all()

    email_accounts = db.scalars(
        select(EmailAccount).where(EmailAccount.user_id == current_user.id)
    ).all()

    account_ids = [a.id for a in email_accounts]

    raw_emails: list = []
    if account_ids:
        raw_emails = db.scalars(
            select(RawEmail).where(RawEmail.email_account_id.in_(account_ids))
        ).all()

    app_list = []
    for app in applications:
        jd = jd_by_app.get(app.id)
        app_list.append({
            "id": app.id,
            "user_id": app.user_id,
            "company_id": app.company_id,
            "role": app.role,
            "status": app.status,
            "source_url": app.source_url,
            "date_applied": app.date_applied,
            "notes": app.notes,
            "created_at": app.created_at,
            "job_description": {
                "id": jd.id,
                "application_id": jd.application_id,
                "raw_text": jd.raw_text,
                "captured_at": jd.captured_at,
            } if jd else None,
        })

    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "created_at": current_user.created_at,
        },
        "companies": [
            {
                "id": c.id,
                "user_id": c.user_id,
                "name": c.name,
                "normalized_name": c.normalized_name,
                "location": c.location,
                "link": c.link,
                "created_at": c.created_at,
            }
            for c in companies
        ],
        "applications": app_list,
        "interviews": [
            {
                "id": i.id,
                "application_id": i.application_id,
                "round_type": i.round_type,
                "scheduled_at": i.scheduled_at,
                "outcome": i.outcome,
                "notes": i.notes,
                "created_at": i.created_at,
            }
            for i in interviews
        ],
        "email_accounts": [
            {
                "id": a.id,
                "email": a.email,
                "last_polled_at": a.last_polled_at,
                "created_at": a.created_at,
            }
            for a in email_accounts
        ],
        "raw_emails": [
            {
                "id": r.id,
                "gmail_message_id": r.gmail_message_id,
                "subject": r.subject,
                "sender": r.sender,
                "received_at": r.received_at,
                "body_snippet": r.body_snippet,
                "gemini_signal": r.gemini_signal,
                "gemini_confidence": r.gemini_confidence,
                "linked_application_id": r.linked_application_id,
                "created_at": r.created_at,
            }
            for r in raw_emails
        ],
    }


@router.delete("/users/me", status_code=204)
@limiter.limit("3/hour")
def delete_user(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """
    Delete the authenticated user and all their data.

    For each connected Gmail account: cancel the poll job (best effort) and
    revoke the OAuth token (best effort). Then delete the user row — ON DELETE
    CASCADE handles all child rows.
    """
    accounts = db.scalars(
        select(EmailAccount).where(EmailAccount.user_id == current_user.id)
    ).all()

    for account in accounts:
        try:
            scheduler.remove_job(f"poll_{account.id}")
        except JobLookupError:
            pass  # job not registered yet — ignore gracefully

        try:
            access_token = decrypt_token(account.access_token)
            http_requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": access_token},
                timeout=5,
            )
        except Exception as exc:
            _logger.warning(
                "Token revocation failed during user deletion",
                extra={"error_type": type(exc).__name__, "user_id": str(current_user.id)},
            )

    db.delete(current_user)
    db.commit()
    return Response(status_code=204)
