import os
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.services.email_application_service import process_email_signal
from app.services.gemini_service import classify_email
from app.utils.email_filter import is_job_related
from app.utils.encryption import decrypt_token, encrypt_token
from app.utils.gmail_client import GmailClientInterface, RealGmailClient
from app.utils.logging import get_logger

_logger = get_logger("gmail_poller")


def poll_gmail_account(
    account_id: str, gmail_client: GmailClientInterface | None = None
) -> None:
    """
    Poll a single Gmail account for new emails.

    Opens its own DB session (APScheduler runs in a thread pool, not the
    async event loop).  Patches welcome ``gmail_client`` for tests via
    MockGmailClient — avoids hitting the real Gmail API.
    """
    db = SessionLocal()
    try:
        account = db.scalar(
            select(EmailAccount).where(EmailAccount.id == uuid.UUID(account_id))
        )
        if not account:
            _logger.warning(
                "EmailAccount not found",
                extra={"email_account_id": account_id, "action_taken": "account_not_found"},
            )
            return

        # Decrypt stored tokens
        try:
            access_token = decrypt_token(account.access_token)
            refresh_token = decrypt_token(account.refresh_token)
        except ValueError:
            _logger.warning(
                "Token decryption failed — skipping account",
                exc_info=True,
                extra={"email_account_id": account_id, "action_taken": "token_decrypt_error"},
            )
            return

        # Build OAuth credentials from stored tokens
        expiry = account.token_expiry
        if expiry is not None and expiry.tzinfo is not None:
            expiry = expiry.replace(tzinfo=None)  # Google auth expects naive UTC datetime
        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            expiry=expiry,
        )

        # Refresh if expired — update stored ciphertext and continue
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                account.access_token = encrypt_token(credentials.token)
                account.refresh_token = encrypt_token(credentials.refresh_token)
                if credentials.expiry:
                    account.token_expiry = credentials.expiry
                db.commit()
            except Exception as exc:
                _logger.warning(
                    "Token refresh failed — skipping account",
                    exc_info=True,
                    extra={
                        "email_account_id": account_id,
                        "action_taken": "token_refresh_failed",
                        "error_type": type(exc).__name__,
                    },
                )
                return

        if gmail_client is None:
            gmail_client = RealGmailClient(credentials)

        since = account.last_polled_at or (
            datetime.now(timezone.utc) - timedelta(days=30)
        )

        # Page loop — follow nextPageToken until exhausted
        page_token = None
        while True:
            result = gmail_client.get_messages_since(account_id, since, page_token)

            for msg_stub in result.get("messages", []):
                message_id = msg_stub["id"]

                # Deduplication — skip if already stored
                if db.scalar(
                    select(RawEmail).where(RawEmail.gmail_message_id == message_id)
                ):
                    _logger.info(
                        "Duplicate message skipped",
                        extra={
                            "gmail_message_id": message_id,
                            "email_account_id": account_id,
                            "action_taken": "dedup_skip",
                        },
                    )
                    continue

                detail = gmail_client.get_message_detail(message_id)

                headers = {
                    h["name"]: h["value"]
                    for h in detail.get("payload", {}).get("headers", [])
                }
                subject = headers.get("Subject", "")
                sender = headers.get("From", "")
                date_str = headers.get("Date", "")

                try:
                    received_at = parsedate_to_datetime(date_str) if date_str else None
                except Exception:
                    received_at = datetime.now(timezone.utc)

                body_snippet = detail.get("snippet", "")[:500]  # explicit truncation

                # Pre-filter: skip non-job emails — do NOT write to raw_emails
                if not is_job_related(sender, subject):
                    _logger.info(
                        "Email pre-filtered",
                        extra={
                            "gmail_message_id": message_id,
                            "email_account_id": account_id,
                            "action_taken": "pre_filter_skip",
                        },
                    )
                    continue

                # Classify with Gemini before storing
                classification = classify_email(subject, sender, body_snippet)

                raw_email = RawEmail(
                    email_account_id=account.id,
                    gmail_message_id=message_id,
                    subject=subject,
                    sender=sender,
                    received_at=received_at,
                    body_snippet=body_snippet,
                    gemini_signal=classification.signal,
                    gemini_confidence=classification.confidence,
                )
                try:
                    db.add(raw_email)
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    _logger.info(
                        "Skipping duplicate email",
                        extra={
                            "gmail_message_id": message_id,
                            "email_account_id": account_id,
                            "action_taken": "dedup_skip",
                        },
                    )
                    continue

                _logger.info(
                    "Email classified and stored",
                    extra={
                        "gmail_message_id": message_id,
                        "email_account_id": account_id,
                        "gemini_signal": classification.signal,
                        "gemini_confidence": classification.confidence,
                        "action_taken": "stored",
                    },
                )

                # Trigger application status update for actionable signals
                _actionable = {"APPLIED", "INTERVIEW", "OFFER", "REJECTED"}
                if classification.signal in _actionable:
                    process_email_signal(
                        db, account.user_id, raw_email, classification
                    )

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        account.last_polled_at = datetime.now(timezone.utc)
        db.commit()

        # Retry pass — re-classify any PARSE_ERROR emails that were never linked.
        # These are emails Gemini failed on (rate limit, network blip) in a previous
        # poll.  The gmail_message_id dedup check would skip them on re-fetch, so
        # the only way to recover them is to retry classification here.
        _actionable = {"APPLIED", "INTERVIEW", "OFFER", "REJECTED"}
        parse_errors = db.scalars(
            select(RawEmail).where(
                RawEmail.email_account_id == account.id,
                RawEmail.gemini_signal == "PARSE_ERROR",
                RawEmail.linked_application_id.is_(None),
            )
        ).all()
        for raw_email in parse_errors:
            classification = classify_email(
                raw_email.subject, raw_email.sender, raw_email.body_snippet
            )
            raw_email.gemini_signal = classification.signal
            raw_email.gemini_confidence = classification.confidence
            db.commit()
            _logger.info(
                "PARSE_ERROR email reclassified",
                extra={
                    "gmail_message_id": raw_email.gmail_message_id,
                    "email_account_id": account_id,
                    "gemini_signal": classification.signal,
                    "gemini_confidence": classification.confidence,
                    "action_taken": "parse_error_retry",
                },
            )
            if classification.signal in _actionable:
                process_email_signal(db, account.user_id, raw_email, classification)

    except Exception as exc:
        _logger.error(
            "Poll job failed",
            exc_info=True,
            extra={
                "email_account_id": account_id,
                "action_taken": "poll_error",
                "error_type": type(exc).__name__,
            },
        )
    finally:
        db.close()
