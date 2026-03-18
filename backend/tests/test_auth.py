import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


def test_get_me_valid_jwt_returns_200(client, auth_headers, test_user):
    resp = client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == str(test_user.id)
    assert data["email"] == test_user.email
    assert "created_at" in data


def test_get_me_invalid_jwt_returns_401(client):
    resp = client.get("/auth/me", headers={"Authorization": "Bearer not.a.valid.token"})
    assert resp.status_code == 401


def test_get_me_no_token_returns_401(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_get_me_creates_user_on_first_login(client, db: Session, make_auth_token):
    new_id = str(uuid.uuid4())
    new_email = f"new_{uuid.uuid4().hex[:8]}@example.com"
    headers = {"Authorization": f"Bearer {make_auth_token(new_id, new_email)}"}

    resp = client.get("/auth/me", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == new_id
    assert data["email"] == new_email

    # Confirm the row exists in the DB within this transaction
    user = db.scalar(select(User).where(User.id == uuid.UUID(new_id)))
    assert user is not None
    assert user.email == new_email


def test_get_me_no_duplicate_on_subsequent_login(
    client, db: Session, test_user, auth_headers
):
    # Call /auth/me twice with the same JWT
    resp1 = client.get("/auth/me", headers=auth_headers)
    resp2 = client.get("/auth/me", headers=auth_headers)

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]

    # Exactly one row for this email
    count = db.scalar(
        select(func.count()).select_from(User).where(User.email == test_user.email)
    )
    assert count == 1


def test_export_returns_501(client, auth_headers):
    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 501


def test_delete_user_returns_501(client, auth_headers):
    resp = client.delete("/users/me", headers=auth_headers)
    assert resp.status_code == 501
