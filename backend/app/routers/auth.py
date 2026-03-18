import requests as http_requests

from apscheduler.jobstores.base import JobLookupError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import User, get_current_user
from app.dependencies.rate_limit import limiter
from app.models.email_account import EmailAccount
from app.scheduler import scheduler
from app.schemas.user import UserResponse
from app.utils.encryption import decrypt_token
from app.utils.logging import get_logger

router = APIRouter()
_logger = get_logger("auth")


@router.get("/auth/me", response_model=UserResponse)
@limiter.limit("60/minute")
def get_me(request: Request, current_user: User = Depends(get_current_user)) -> User:
    _logger.debug("Auth successful", extra={"user_id": str(current_user.id)})
    return current_user


@router.get("/users/me/export")
@limiter.limit("5/hour")
def export_user_data(request: Request, _: User = Depends(get_current_user)):
    # Implemented in chunk 8
    raise HTTPException(status_code=501, detail="Not yet implemented")


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
