import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from jose import jwt as jose_jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

load_dotenv()

from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402, F401 — ensures model is registered

DATABASE_URL_DIRECT = os.environ["DATABASE_URL_DIRECT"]
SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]

test_engine = create_engine(DATABASE_URL_DIRECT, pool_pre_ping=True)


@pytest.fixture
def db():
    """
    Yields a SQLAlchemy Session bound to an open transaction that is rolled
    back after each test.  Any session.commit() calls inside application code
    only release a SAVEPOINT; the outer transaction stays open until rollback.
    """
    connection = test_engine.connect()
    trans = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


@pytest.fixture
def test_user(db: Session) -> User:
    """Creates a real User row within the test transaction."""
    user = User(
        id=uuid.uuid4(),
        email=f"test_{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def make_auth_token():
    """Factory that signs a Supabase-style JWT for any user id/email."""

    def _make(user_id: str, email: str) -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "aud": "authenticated",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return jose_jwt.encode(payload, SUPABASE_JWT_SECRET, algorithm="HS256")

    return _make


@pytest.fixture
def auth_headers(test_user: User, make_auth_token) -> dict:
    """Bearer headers for the test_user."""
    token = make_auth_token(str(test_user.id), test_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_user(db: Session) -> User:
    """A second real User row for ownership/isolation tests."""
    user = User(
        id=uuid.uuid4(),
        email=f"other_{uuid.uuid4().hex[:8]}@example.com",
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def other_auth_headers(other_user: User, make_auth_token) -> dict:
    """Bearer headers for other_user."""
    token = make_auth_token(str(other_user.id), other_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(db: Session):
    """
    TestClient with get_db overridden to use the test transaction session.
    Dependency override is cleared after the test.
    """

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()
