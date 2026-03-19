import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.models.email_account import EmailAccount
from app.models.gmail_oauth_state import GmailOAuthState
from app.models.user import User
from app.utils.encryption import decrypt_token, encrypt_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state(db: Session, user_id: uuid.UUID, expires_delta: timedelta) -> str:
    """Insert a GmailOAuthState row and return its state_token."""
    token = "test_state_" + uuid.uuid4().hex
    row = GmailOAuthState(
        state_token=token,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + expires_delta,
    )
    db.add(row)
    db.flush()
    return token


def _make_mock_credentials(
    token: str = "fake_access_token",
    refresh_token: str = "fake_refresh_token",
) -> MagicMock:
    creds = MagicMock()
    creds.token = token
    creds.refresh_token = refresh_token
    creds.expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    return creds


def _make_mock_flow(credentials: MagicMock) -> MagicMock:
    flow = MagicMock()
    flow.credentials = credentials
    flow.code_verifier = "test_code_verifier_value"
    flow.oauth2session._state = "lib_generated_state"
    flow.authorization_url.return_value = (
        "https://accounts.google.com/o/oauth2/auth?client_id=test&state=lib_generated_state",
        "lib_generated_state",
    )
    return flow


# ---------------------------------------------------------------------------
# GET /gmail/connect
# ---------------------------------------------------------------------------

class TestGmailConnect:
    def test_connect_returns_authorization_url(self, client, auth_headers, db, test_user):
        mock_flow = _make_mock_flow(_make_mock_credentials())

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow):
            response = client.get("/gmail/connect", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()
        assert "authorization_url" in data
        assert "accounts.google.com" in data["authorization_url"]

    def test_connect_requires_auth(self, client):
        response = client.get("/gmail/connect")
        assert response.status_code == 401

    def test_connect_creates_state_token_in_db(self, client, auth_headers, db, test_user):
        from sqlalchemy import select

        mock_flow = _make_mock_flow(_make_mock_credentials())

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow):
            client.get("/gmail/connect", headers=auth_headers)

        states = db.scalars(
            select(GmailOAuthState).where(GmailOAuthState.user_id == test_user.id)
        ).all()
        assert len(states) == 1


# ---------------------------------------------------------------------------
# GET /gmail/callback
# ---------------------------------------------------------------------------

class TestGmailCallback:
    def test_callback_with_valid_state_stores_encrypted_tokens(
        self, client, db, test_user
    ):
        state = _make_state(db, test_user.id, timedelta(minutes=10))
        creds = _make_mock_credentials()
        mock_flow = _make_mock_flow(creds)

        mock_gmail_service = MagicMock()
        mock_gmail_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "connected@gmail.com"
        }

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow):
            with patch("app.routers.gmail.google_build", return_value=mock_gmail_service):
                response = client.get(
                    f"/gmail/callback?state={state}&code=auth_code_123",
                    follow_redirects=False,
                )

        # Should redirect to /settings
        assert response.status_code in (302, 307)
        assert "/settings" in response.headers["location"]

        # Token should be stored encrypted — ciphertext differs from plaintext
        from sqlalchemy import select
        account = db.scalar(
            select(EmailAccount).where(
                EmailAccount.user_id == test_user.id,
                EmailAccount.email == "connected@gmail.com",
            )
        )
        assert account is not None
        assert account.access_token != creds.token
        assert account.refresh_token != creds.refresh_token
        # Decrypting should recover the originals
        assert decrypt_token(account.access_token) == creds.token
        assert decrypt_token(account.refresh_token) == creds.refresh_token

    def test_callback_with_expired_state_returns_400(self, client, db, test_user):
        state = _make_state(db, test_user.id, timedelta(minutes=-1))  # already expired

        response = client.get(f"/gmail/callback?state={state}&code=anything")
        assert response.status_code == 400
        assert "expired" in response.json()["detail"].lower()

    def test_callback_with_unknown_state_returns_400(self, client, db):
        response = client.get("/gmail/callback?state=nonexistent_state&code=anything")
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    def test_callback_without_jwt_does_not_return_401(self, client, db, test_user):
        """Callback has no auth dependency — absence of JWT must not cause a 401."""
        state = _make_state(db, test_user.id, timedelta(minutes=10))
        creds = _make_mock_credentials()
        mock_flow = _make_mock_flow(creds)

        mock_gmail_service = MagicMock()
        mock_gmail_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "nojwt@gmail.com"
        }

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow):
            with patch("app.routers.gmail.google_build", return_value=mock_gmail_service):
                # No Authorization header
                response = client.get(
                    f"/gmail/callback?state={state}&code=auth_code_456",
                    follow_redirects=False,
                )

        assert response.status_code != 401

    def test_callback_state_token_deleted_after_use(self, client, db, test_user):
        """State token is single-use — must be deleted on success."""
        from sqlalchemy import select

        state = _make_state(db, test_user.id, timedelta(minutes=10))
        creds = _make_mock_credentials()
        mock_flow = _make_mock_flow(creds)

        mock_gmail_service = MagicMock()
        mock_gmail_service.users.return_value.getProfile.return_value.execute.return_value = {
            "emailAddress": "once@gmail.com"
        }

        with patch("app.routers.gmail.build_oauth_flow", return_value=mock_flow):
            with patch("app.routers.gmail.google_build", return_value=mock_gmail_service):
                client.get(
                    f"/gmail/callback?state={state}&code=code",
                    follow_redirects=False,
                )

        remaining = db.scalar(
            select(GmailOAuthState).where(GmailOAuthState.state_token == state)
        )
        assert remaining is None


# ---------------------------------------------------------------------------
# DELETE /gmail/disconnect/{account_id}
# ---------------------------------------------------------------------------

class TestGmailDisconnect:
    def _make_account(self, db: Session, user_id: uuid.UUID, email: str = "test@gmail.com") -> EmailAccount:
        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=user_id,
            email=email,
            access_token=encrypt_token("access"),
            refresh_token=encrypt_token("refresh"),
        )
        db.add(account)
        db.flush()
        return account

    def test_disconnect_non_owned_account_returns_404(
        self, client, db, test_user, other_user, auth_headers
    ):
        account = self._make_account(db, other_user.id)
        with patch("app.routers.gmail.http_requests.post"):
            response = client.delete(
                f"/gmail/disconnect/{account.id}", headers=auth_headers
            )
        assert response.status_code == 404

    def test_disconnect_unknown_account_returns_404(self, client, db, auth_headers):
        response = client.delete(
            f"/gmail/disconnect/{uuid.uuid4()}", headers=auth_headers
        )
        assert response.status_code == 404

    def test_disconnect_owned_account_returns_204(
        self, client, db, test_user, auth_headers
    ):
        from sqlalchemy import select

        account = self._make_account(db, test_user.id)
        account_id = account.id

        with patch("app.routers.gmail.http_requests.post"):
            response = client.delete(
                f"/gmail/disconnect/{account_id}", headers=auth_headers
            )

        assert response.status_code == 204
        gone = db.scalar(
            select(EmailAccount).where(EmailAccount.id == account_id)
        )
        assert gone is None

    def test_disconnect_requires_auth(self, client, db):
        response = client.delete(f"/gmail/disconnect/{uuid.uuid4()}")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# GET /gmail/accounts
# ---------------------------------------------------------------------------

class TestGmailAccounts:
    def test_accounts_returns_empty_list(self, client, auth_headers):
        response = client.get("/gmail/accounts", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_accounts_returns_connected_accounts(self, client, db, test_user, auth_headers):
        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=test_user.id,
            email="listed@gmail.com",
            access_token=encrypt_token("access"),
            refresh_token=encrypt_token("refresh"),
        )
        db.add(account)
        db.flush()

        response = client.get("/gmail/accounts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["email"] == "listed@gmail.com"
        # Tokens must NOT appear in the response
        assert "access_token" not in data[0]
        assert "refresh_token" not in data[0]

    def test_accounts_scoped_to_current_user(
        self, client, db, test_user, other_user, auth_headers
    ):
        # Account belonging to other user
        db.add(EmailAccount(
            id=uuid.uuid4(),
            user_id=other_user.id,
            email="other@gmail.com",
            access_token=encrypt_token("a"),
            refresh_token=encrypt_token("r"),
        ))
        db.flush()

        response = client.get("/gmail/accounts", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    def test_accounts_requires_auth(self, client):
        response = client.get("/gmail/accounts")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /users/me — scheduler jobs + cascade
# ---------------------------------------------------------------------------

class TestDeleteUserMe:
    def _make_account(self, db: Session, user_id: uuid.UUID, email: str) -> EmailAccount:
        account = EmailAccount(
            id=uuid.uuid4(),
            user_id=user_id,
            email=email,
            access_token=encrypt_token("access"),
            refresh_token=encrypt_token("refresh"),
        )
        db.add(account)
        db.flush()
        return account

    def test_delete_user_calls_remove_job_for_each_account(
        self, client, db, test_user, auth_headers
    ):
        account1 = self._make_account(db, test_user.id, "a@gmail.com")
        account2 = self._make_account(db, test_user.id, "b@gmail.com")
        # Capture IDs before the delete — SQLAlchemy expunges objects after cascade
        id1, id2 = account1.id, account2.id

        with patch("app.routers.auth.scheduler") as mock_scheduler:
            with patch("app.routers.auth.http_requests.post"):
                response = client.delete("/users/me", headers=auth_headers)

        assert response.status_code == 204
        job_ids = {call.args[0] for call in mock_scheduler.remove_job.call_args_list}
        assert f"poll_{id1}" in job_ids
        assert f"poll_{id2}" in job_ids

    def test_delete_user_ignores_missing_jobs(
        self, client, db, test_user, auth_headers
    ):
        """JobLookupError on remove_job must not bubble up as a 500."""
        from apscheduler.jobstores.base import JobLookupError

        self._make_account(db, test_user.id, "c@gmail.com")

        with patch("app.routers.auth.scheduler") as mock_scheduler:
            mock_scheduler.remove_job.side_effect = JobLookupError("poll_xyz")
            with patch("app.routers.auth.http_requests.post"):
                response = client.delete("/users/me", headers=auth_headers)

        assert response.status_code == 204

    def test_delete_user_cascades_accounts(
        self, client, db, test_user, auth_headers
    ):
        """Deleting the user row must cascade to email_accounts."""
        from sqlalchemy import select

        account = self._make_account(db, test_user.id, "d@gmail.com")
        account_id = account.id
        user_id = test_user.id

        with patch("app.routers.auth.scheduler"):
            with patch("app.routers.auth.http_requests.post"):
                response = client.delete("/users/me", headers=auth_headers)

        assert response.status_code == 204

        gone_user = db.scalar(select(User).where(User.id == user_id))
        gone_account = db.scalar(select(EmailAccount).where(EmailAccount.id == account_id))
        assert gone_user is None
        assert gone_account is None

    def test_delete_user_with_no_accounts(self, client, db, test_user, auth_headers):
        """User with no Gmail accounts can still be deleted cleanly."""
        with patch("app.routers.auth.scheduler"):
            response = client.delete("/users/me", headers=auth_headers)
        assert response.status_code == 204


# ---------------------------------------------------------------------------
# Encryption utility unit tests
# ---------------------------------------------------------------------------

class TestEncryption:
    def test_round_trip(self):
        plaintext = "my-secret-token-value"
        encrypted = encrypt_token(plaintext)
        assert encrypted != plaintext
        assert decrypt_token(encrypted) == plaintext

    def test_different_ciphertexts_for_same_plaintext(self):
        """Fernet uses random IVs — two encryptions of the same value differ."""
        plaintext = "same-token"
        assert encrypt_token(plaintext) != encrypt_token(plaintext)

    def test_decrypt_invalid_raises_value_error(self):
        with pytest.raises(ValueError):
            decrypt_token("not-valid-ciphertext")
