import os
from typing import List

import requests as http_requests
from apscheduler.jobstores.base import JobLookupError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from googleapiclient.discovery import build as google_build
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import User, get_current_user
from app.dependencies.rate_limit import get_ip_key, limiter
from app.jobs.poll_job import poll_gmail_account
from app.models.email_account import EmailAccount
from app.scheduler import scheduler
from app.schemas.gmail import EmailAccountResponse
from app.services.gmail_oauth_service import (
    build_oauth_flow,
    consume_state_token,
    create_state_token,
    store_gmail_tokens,
)
from app.utils.logging import get_logger

router = APIRouter()
_logger = get_logger("gmail")


@router.get("/gmail/connect")
@limiter.limit("10/minute")
def gmail_connect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Initiate Gmail OAuth flow — returns an authorization URL."""
    flow = build_oauth_flow()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
    )
    state_token = create_state_token(
        db, current_user.id, code_verifier=flow.code_verifier
    )
    # Replace the library-generated state with our DB-backed CSRF token
    authorization_url = authorization_url.replace(
        f"state={flow.oauth2session._state}", f"state={state_token}"
    )
    return {"authorization_url": authorization_url}


@router.get("/gmail/callback")
@limiter.limit("20/minute", key_func=get_ip_key)
def gmail_callback(
    request: Request,
    state: str,
    code: str,
    db: Session = Depends(get_db),
):
    """
    Handle Google's OAuth redirect.

    NO auth dependency — there is no JWT on this request.
    User identity comes exclusively from the gmail_oauth_states DB row.
    """
    user_id, code_verifier = consume_state_token(db, state)

    flow = build_oauth_flow()
    flow.fetch_token(code=code, code_verifier=code_verifier)
    credentials = flow.credentials

    # Fetch the connected email address from Gmail API
    gmail = google_build("gmail", "v1", credentials=credentials)
    profile = gmail.users().getProfile(userId="me").execute()
    email = profile["emailAddress"]

    account = store_gmail_tokens(db, user_id, credentials, email)
    scheduler.add_job(
        poll_gmail_account,
        trigger="interval",
        minutes=15,
        id=f"poll_{account.id}",
        args=[str(account.id)],
        max_instances=1,
        replace_existing=True,
    )

    _logger.info("Gmail account connected", extra={"user_id": str(user_id)})

    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    return RedirectResponse(url=f"{frontend_url}/settings")


@router.delete("/gmail/disconnect/{account_id}", status_code=204)
@limiter.limit("10/minute")
def gmail_disconnect(
    account_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke Gmail access and delete the email_accounts row."""
    from app.utils.encryption import decrypt_token

    account = db.scalar(
        select(EmailAccount).where(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id,
        )
    )
    if not account:
        raise HTTPException(status_code=404)

    # Best effort revocation — don't fail the request if Google is unreachable
    try:
        access_token = decrypt_token(account.access_token)
        http_requests.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": access_token},
            timeout=5,
        )
    except Exception as exc:
        _logger.warning(
            "Token revocation failed",
            extra={"error_type": type(exc).__name__, "user_id": str(current_user.id)},
        )

    try:
        scheduler.remove_job(f"poll_{account.id}")
    except JobLookupError:
        pass

    db.delete(account)
    db.commit()


@router.get("/gmail/accounts", response_model=List[EmailAccountResponse])
@limiter.limit("30/minute")
def gmail_accounts(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List connected Gmail accounts for the current user (email field only, no tokens)."""
    accounts = db.scalars(
        select(EmailAccount).where(EmailAccount.user_id == current_user.id)
    ).all()
    return accounts


@router.post("/gmail/accounts/{account_id}/poll")
@limiter.limit("10/hour")
def gmail_poll(
    account_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger manual email poll for an account. Implemented in chunk 10."""
    account = db.scalar(
        select(EmailAccount).where(
            EmailAccount.id == account_id,
            EmailAccount.user_id == current_user.id,
        )
    )
    if not account:
        raise HTTPException(status_code=404)

    poll_gmail_account(str(account_id))
    return {"detail": "Poll triggered"}
