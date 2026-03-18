"""Tests for APScheduler setup and job registration (chunk 9)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models.email_account import EmailAccount
from app.models.gmail_oauth_state import GmailOAuthState
from app.utils.encryption import encrypt_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(db: Session, user_id: uuid.UUID, expires_delta: timedelta) -> str:
    token = "sched_" + uuid.uuid4().hex
    db.add(GmailOAuthState(
        state_token=token,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + expires_delta,
    ))
    db.flush()
    return token


def _make_mock_flow(creds: MagicMock) -> MagicMock:
    flow = MagicMock()
    flow.credentials = creds
    flow.authorization_url.return_value = ("https://accounts.google.com/...", "state")
    return flow


# ---------------------------------------------------------------------------
# Lifespan startup
# ---------------------------------------------------------------------------

class TestLifespan:
    def test_scheduler_starts_on_lifespan(self):
        """scheduler.start() is called when the app starts up."""
        with patch("app.main.scheduler") as mock_sched, \
             patch("app.main.SessionLocal") as mock_sess_cls:
            mock_db = MagicMock()
            mock_sess_cls.return_value = mock_db
            mock_db.scalars.return_value.all.return_value = []

            with TestClient(app, raise_server_exceptions=True):
                mock_sched.start.assert_called_once()

        mock_sched.shutdown.assert_called_once_with(wait=False)

    def test_lifespan_registers_cleanup_and_keepalive_jobs(self):
        """cleanup_oauth_states and keepalive jobs are registered at startup."""
        with patch("app.main.scheduler") as mock_sched, \
             patch("app.main.SessionLocal") as mock_sess_cls:
            mock_db = MagicMock()
            mock_sess_cls.return_value = mock_db
            mock_db.scalars.return_value.all.return_value = []

            with TestClient(app, raise_server_exceptions=True):
                pass

        job_ids = {c.kwargs["id"] for c in mock_sched.add_job.call_args_list}
        assert "cleanup_oauth_states" in job_ids
        assert "keepalive" in job_ids


# ---------------------------------------------------------------------------
# Cleanup job
# ---------------------------------------------------------------------------

class TestCleanupJob:
    def test_deletes_expired_rows_and_leaves_valid_rows(self, db, test_user):
        """cleanup_expired_oauth_states removes expired rows but not valid ones."""
        from app.jobs.cleanup_job import cleanup_expired_oauth_states

        now = datetime.now(timezone.utc)

        expired = GmailOAuthState(
            state_token="exp_" + uuid.uuid4().hex,
            user_id=test_user.id,
            expires_at=now - timedelta(hours=1),
        )
        valid = GmailOAuthState(
            state_token="val_" + uuid.uuid4().hex,
            user_id=test_user.id,
            expires_at=now + timedelta(hours=1),
        )
        db.add_all([expired, valid])
        db.flush()

        expired_token = expired.state_token
        valid_token = valid.state_token

        # Wrap the test session: delegate all calls but prevent close() from
        # invalidating the session for subsequent assertions.
        wrapped = MagicMock(wraps=db)
        wrapped.close = MagicMock()

        with patch("app.jobs.cleanup_job.SessionLocal", return_value=wrapped):
            cleanup_expired_oauth_states()

        wrapped.close.assert_called_once()

        remaining = {
            r.state_token
            for r in db.scalars(
                select(GmailOAuthState).where(GmailOAuthState.user_id == test_user.id)
            ).all()
        }
        assert valid_token in remaining
        assert expired_token not in remaining


# ---------------------------------------------------------------------------
# Poll job registration / deregistration
# ---------------------------------------------------------------------------

class TestPollJobScheduling:
    def test_poll_job_registered_after_gmail_connect(
        self, client, db, test_user, auth_headers
    ):
        """scheduler.add_job is called with poll_{account_id} after OAuth callback."""
        state = _make_state(db, test_user.id, timedelta(minutes=10))

        creds = MagicMock()
        creds.token = "at"
        creds.refresh_token = "rt"
        creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
        mock_flow = _make_mock_flow(creds)

        mock_gmail = MagicMock()
        mock_gmail.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "poll_test@gmail.com"
        }

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow), \
             patch("app.routers.gmail.google_build", return_value=mock_gmail), \
             patch("app.routers.gmail.scheduler") as mock_sched:
            client.get(
                f"/gmail/callback?state={state}&code=code",
                follow_redirects=False,
            )

        mock_sched.add_job.assert_called_once()
        registered_id = mock_sched.add_job.call_args.kwargs["id"]

        account = db.scalar(
            select(EmailAccount).where(
                EmailAccount.user_id == test_user.id,
                EmailAccount.email == "poll_test@gmail.com",
            )
        )
        assert account is not None
        assert registered_id == f"poll_{account.id}"

    def test_poll_job_removed_after_gmail_disconnect(
        self, client, db, test_user, auth_headers
    ):
        """scheduler.remove_job is called with poll_{account_id} on disconnect."""
        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=test_user.id,
            email="disc@gmail.com",
            access_token=encrypt_token("at"),
            refresh_token=encrypt_token("rt"),
        )
        db.add(account)
        db.flush()
        account_id = account.id

        with patch("app.routers.gmail.scheduler") as mock_sched, \
             patch("app.routers.gmail.http_requests.post"):
            client.delete(f"/gmail/disconnect/{account_id}", headers=auth_headers)

        mock_sched.remove_job.assert_called_once_with(f"poll_{account_id}")

    def test_disconnect_ignores_missing_poll_job(
        self, client, db, test_user, auth_headers
    ):
        """JobLookupError on remove_job during disconnect must not produce a 500."""
        from apscheduler.jobstores.base import JobLookupError

        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=test_user.id,
            email="nojob@gmail.com",
            access_token=encrypt_token("at"),
            refresh_token=encrypt_token("rt"),
        )
        db.add(account)
        db.flush()

        with patch("app.routers.gmail.scheduler") as mock_sched, \
             patch("app.routers.gmail.http_requests.post"):
            mock_sched.remove_job.side_effect = JobLookupError("poll_x")
            response = client.delete(
                f"/gmail/disconnect/{account.id}", headers=auth_headers
            )

        assert response.status_code == 204
