import os
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.database import get_db

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
SUPABASE_URL = os.environ["SUPABASE_URL"]

_bearer = HTTPBearer()


# Stub — replaced by the real SQLAlchemy model in chunk 3.
# Update the import in get_current_user at that point.
@dataclass
class User:
    id: str
    email: str
    created_at: datetime = field(default_factory=datetime.utcnow)


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
    payload = verify_supabase_jwt(credentials.credentials)
    from app.services.user_service import get_or_create_user  # avoid circular import
    return get_or_create_user(db, id=payload["sub"], email=payload["email"])
