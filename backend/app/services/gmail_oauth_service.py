import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from google_auth_oauthlib.flow import Flow
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email_account import EmailAccount
from app.models.gmail_oauth_state import GmailOAuthState
from app.utils.encryption import encrypt_token

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def build_oauth_flow() -> Flow:
    """Create a google_auth_oauthlib Flow for Gmail OAuth."""
    redirect_uri = os.getenv("BACKEND_URL", "http://localhost:8000") + "/gmail/callback"
    client_config = {
        "web": {
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config, scopes=GMAIL_SCOPES, redirect_uri=redirect_uri
    )
    # Disable PKCE — the code verifier is not persisted between
    # /gmail/connect and /gmail/callback (stateless HTTP), so PKCE
    # cannot complete. Disable it entirely.
    flow.code_verifier = None
    flow.oauth2session._client.code_challenge_method = None
    return flow


def create_state_token(db: Session, user_id: uuid.UUID) -> str:
    """Generate a CSRF state token and persist it with a 10-minute expiry."""
    token = secrets.token_urlsafe(32)
    state = GmailOAuthState(
        state_token=token,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    db.add(state)
    db.commit()
    return token


def consume_state_token(db: Session, state_token: str) -> uuid.UUID:
    """
    Validate and consume a state token (single-use CSRF protection).

    Raises HTTP 400 if the token is unknown or expired.
    Deletes the row on success — leaving it open is a security regression.
    """
    row = db.scalar(
        select(GmailOAuthState).where(GmailOAuthState.state_token == state_token)
    )
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid state")

    if row.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="State token expired")

    user_id = row.user_id
    db.delete(row)
    db.commit()
    return user_id


def store_gmail_tokens(db: Session, user_id: uuid.UUID, credentials, email: str) -> EmailAccount:
    """
    Upsert an email_accounts row with encrypted OAuth tokens.

    Fresh credentials from Google OAuth are plaintext — encrypt before storing.
    Only updates refresh_token if Google returned one (it won't on reconnects
    unless prompt="consent" was used).
    """
    account = db.scalar(
        select(EmailAccount).where(
            EmailAccount.user_id == user_id,
            EmailAccount.email == email,
        )
    )
    if account is None:
        account = EmailAccount(id=uuid.uuid4(), user_id=user_id, email=email)
        db.add(account)

    account.access_token = encrypt_token(credentials.token)
    if credentials.refresh_token:
        account.refresh_token = encrypt_token(credentials.refresh_token)
    account.token_expiry = credentials.expiry
    db.commit()
    return account
