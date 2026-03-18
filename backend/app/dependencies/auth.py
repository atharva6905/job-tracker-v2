import os
import uuid as uuid_module

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, HTTPException, status  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from jose import JWTError, jwt  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models.user import User  # noqa: E402, F401 — re-exported for router imports

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
SUPABASE_URL = os.environ["SUPABASE_URL"]

_bearer = HTTPBearer()


def verify_supabase_jwt(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated",
            options={"verify_exp": True},
        )
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Lookup-only — returns 401 if the user does not exist."""
    payload = verify_supabase_jwt(credentials.credentials)
    user_id = uuid_module.UUID(payload["sub"])
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_or_create_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Used by /auth/me only — creates the user row on first login."""
    payload = verify_supabase_jwt(credentials.credentials)
    from app.services.user_service import get_or_create_user  # avoid circular import
    return get_or_create_user(db, id=payload["sub"], email=payload["email"])
