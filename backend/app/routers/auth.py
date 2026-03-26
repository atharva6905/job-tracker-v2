import csv
import io
import requests as http_requests

from apscheduler.jobstores.base import JobLookupError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import User, get_current_user, get_or_create_current_user
from app.dependencies.rate_limit import limiter
from app.models.application import Application
from app.models.company import Company
from app.models.email_account import EmailAccount
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
) -> StreamingResponse:
    companies = db.scalars(
        select(Company).where(Company.user_id == current_user.id)
    ).all()
    company_map = {c.id: c.name for c in companies}

    applications = db.scalars(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    ).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["company", "role", "status", "date_applied", "created_at", "source_url", "notes"])
    for app in applications:
        writer.writerow([
            company_map.get(app.company_id, ""),
            app.role,
            app.status,
            str(app.date_applied) if app.date_applied else "",
            str(app.created_at) if app.created_at else "",
            app.source_url or "",
            app.notes or "",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="job-tracker-export.csv"'},
    )


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
