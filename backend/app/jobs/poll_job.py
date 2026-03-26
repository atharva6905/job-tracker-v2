import os
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.models.raw_email import RawEmail
from app.utils.company import normalize_company_name
from app.services.email_application_service import extract_ats_job_id, process_email_signal
from app.services.gemini_service import classify_email, ACTIONABLE_SIGNALS
from app.utils.email_filter import is_job_related
from app.utils.encryption import decrypt_token, encrypt_token
from app.utils.gmail_client import GmailClientInterface, RealGmailClient
from app.utils.logging import get_logger
from app.utils.workday import extract_tenant_from_sender

_logger = get_logger("gmail_poller")


def _load_active_company_names(db: Session, user_id: uuid.UUID) -> set[str]:
    """
    Returns the set of normalized company names for all active (non-terminal)
    applications belonging to this user. Used as a coarse gate before Gemini.
    Active = IN_PROGRESS, APPLIED, INTERVIEW (excludes OFFER, REJECTED).

    Loaded ONCE per poll cycle — do NOT call this per-email; it would change
    semantics and create N+1 queries. The set is intentionally a snapshot:
    if an email transitions an app mid-poll, active_companies still contains
    the company, and the next matching email will attempt a transition (handled
    as a no-op by _apply_transition's invalid-transition guard if needed).
    """
    rows = db.execute(
        select(Company.normalized_name)
        .join(Application, Application.company_id == Company.id)
        .where(
            Application.user_id == user_id,
            Application.status.in_([
                ApplicationStatus.IN_PROGRESS,
                ApplicationStatus.APPLIED,
                ApplicationStatus.INTERVIEW,
            ]),
            Application.deleted_at.is_(None),
        )
    ).scalars().all()
    return set(rows)


def _load_active_workday_tenants(db: Session, user_id: uuid.UUID) -> set[str]:
    """Returns the set of Workday tenant strings for all active applications.

    Used alongside active_companies in the fine gate — an email passes if the
    sender tenant matches any active tenant, even when the Gemini-extracted
    company name doesn't match a known company.
    """
    rows = db.execute(
        select(Application.workday_tenant)
        .where(
            Application.user_id == user_id,
            Application.status.in_([
                ApplicationStatus.IN_PROGRESS,
                ApplicationStatus.APPLIED,
                ApplicationStatus.INTERVIEW,
            ]),
            Application.workday_tenant.isnot(None),
            Application.deleted_at.is_(None),
        )
    ).scalars().all()
    return set(rows)


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

        active_companies = _load_active_company_names(db, account.user_id)
        active_tenants = _load_active_workday_tenants(db, account.user_id)

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

                # Coarse gate: skip Gemini entirely if user has no active applications
                if not active_companies and not active_tenants:
                    _logger.info(
                        "No active applications — skipping email",
                        extra={
                            "gmail_message_id": message_id,
                            "email_account_id": account_id,
                            "action_taken": "no_in_progress_match",
                        },
                    )
                    continue

                # Classify with Gemini before storing
                classification = classify_email(subject, sender, body_snippet)

                # Fine gate: skip if classified company has no matching active application.
                # PARSE_ERROR exception: cannot gate by company (Gemini failed to extract).
                # Store it so the retry loop can re-gate once company name is recovered.
                # Short-circuit on not classification.company to skip normalization when absent.
                if (
                    classification.signal != "PARSE_ERROR"
                    and (
                        not classification.company
                        or normalize_company_name(classification.company) not in active_companies
                    )
                ):
                    # Bypass 1: R-number in subject matches an active app's ats_job_id
                    bypassed = False
                    r_number = extract_ats_job_id(subject)
                    if r_number:
                        has_ats_match = db.scalar(
                            select(Application.id).where(
                                Application.user_id == account.user_id,
                                Application.status.in_([
                                    ApplicationStatus.IN_PROGRESS,
                                    ApplicationStatus.APPLIED,
                                    ApplicationStatus.INTERVIEW,
                                ]),
                                Application.ats_job_id.isnot(None),
                                Application.ats_job_id.contains(r_number),
                                Application.deleted_at.is_(None),
                            )
                        )
                        if has_ats_match:
                            _logger.info(
                                "Fine gate bypassed via ats_job_id match",
                                extra={
                                    "gmail_message_id": message_id,
                                    "email_account_id": account_id,
                                    "gemini_signal": classification.signal,
                                    "action_taken": "fine_gate_ats_bypass",
                                },
                            )
                            bypassed = True

                    # Bypass 2: sender tenant matches an active Workday tenant
                    if not bypassed:
                        sender_tenant = extract_tenant_from_sender(sender)
                        if sender_tenant and sender_tenant in active_tenants:
                            _logger.info(
                                "Fine gate bypassed via tenant match",
                                extra={
                                    "gmail_message_id": message_id,
                                    "email_account_id": account_id,
                                    "gemini_signal": classification.signal,
                                    "action_taken": "fine_gate_tenant_bypass",
                                },
                            )
                            bypassed = True

                    if not bypassed:
                        _logger.info(
                            "Email company has no active application — skipping",
                            extra={
                                "gmail_message_id": message_id,
                                "email_account_id": account_id,
                                "gemini_signal": classification.signal,
                                "action_taken": "no_in_progress_match",
                            },
                        )
                        continue

                raw_email = RawEmail(
                    email_account_id=account.id,
                    gmail_message_id=message_id,
                    subject=subject,
                    sender=sender,
                    received_at=received_at,
                    body_snippet=body_snippet,
                    gemini_signal=classification.signal,
                    gemini_confidence=classification.confidence,
                    gemini_company=classification.company,
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
                if classification.signal in ACTIONABLE_SIGNALS:
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
            raw_email.gemini_company = classification.company
            # Do NOT commit here — defer until after process_email_signal so the
            # signal update and linked_application_id write are in one transaction.
            # process_email_signal calls db.commit() internally via _apply_transition.
            # If the signal is not actionable or no match, commit the signal update below.
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
            # Re-gate: check if company now extracted and matches an active application.
            # active_companies was loaded at poll start — intentionally stale (snapshot).
            # Do not re-query here; the set is correct for this poll cycle.
            if classification.signal in ACTIONABLE_SIGNALS:
                company_matches = (
                    classification.company
                    and normalize_company_name(classification.company) in active_companies
                )
                # Bypass: allow through if subject has an R-number matching an active app
                ats_matches = False
                if not company_matches:
                    retry_r_number = extract_ats_job_id(raw_email.subject or "")
                    if retry_r_number:
                        ats_matches = bool(db.scalar(
                            select(Application.id).where(
                                Application.user_id == account.user_id,
                                Application.status.in_([
                                    ApplicationStatus.IN_PROGRESS,
                                    ApplicationStatus.APPLIED,
                                    ApplicationStatus.INTERVIEW,
                                ]),
                                Application.ats_job_id.isnot(None),
                                Application.ats_job_id.contains(retry_r_number),
                                Application.deleted_at.is_(None),
                            )
                        ))
                # Bypass: allow through if sender tenant matches an active tenant
                tenant_matches = False
                if not company_matches and not ats_matches:
                    retry_tenant = extract_tenant_from_sender(raw_email.sender or "")
                    tenant_matches = bool(retry_tenant and retry_tenant in active_tenants)
                if company_matches or ats_matches or tenant_matches:
                    # process_email_signal commits signal + linked_application_id together
                    process_email_signal(db, account.user_id, raw_email, classification)
                else:
                    db.commit()  # commit signal update only (no match to link)
                    _logger.info(
                        "PARSE_ERROR retry: no active application match — skipping",
                        extra={
                            "gmail_message_id": raw_email.gmail_message_id,
                            "email_account_id": account_id,
                            "gemini_signal": classification.signal,
                            "action_taken": "no_in_progress_match",
                        },
                    )
            else:
                db.commit()  # commit signal update for non-actionable results

        # Cleanup — purge orphaned PARSE_ERROR rows older than 30 days.
        # These are emails Gemini permanently failed on and that were never
        # linked to an application.  Keeping them forever bloats raw_emails.
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        deleted = db.execute(
            delete(RawEmail).where(
                RawEmail.email_account_id == account.id,
                RawEmail.gemini_signal == "PARSE_ERROR",
                RawEmail.linked_application_id.is_(None),
                RawEmail.received_at < cutoff,
            )
        ).rowcount
        db.commit()
        if deleted:
            _logger.info(
                "Purged orphaned PARSE_ERROR emails",
                extra={
                    "email_account_id": account_id,
                    "deleted_count": deleted,
                    "action_taken": "parse_error_cleanup",
                },
            )

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
