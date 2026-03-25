import json
import logging
import os
import time
import uuid as uuid_module
from threading import Lock

from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger(__name__)

import httpx  # noqa: E402
import jwt  # noqa: E402
from fastapi import Depends, HTTPException, status  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: E402
from jwt.algorithms import ECAlgorithm  # noqa: E402
from jwt.exceptions import PyJWTError  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.database import get_db  # noqa: E402
from app.models.user import User  # noqa: E402, F401 — re-exported for router imports

SUPABASE_JWT_SECRET = os.environ["SUPABASE_JWT_SECRET"]
SUPABASE_URL = os.environ["SUPABASE_URL"]

_bearer = HTTPBearer()

# JWKS cache — avoids a round-trip to Supabase on every request
_jwks_keys: list[dict] = []
_jwks_fetched_at: float = 0.0
_jwks_lock = Lock()
_JWKS_TTL = 3600.0  # seconds


def _get_jwks_key(kid: str) -> dict:
    """Return the JWKS public key matching kid, refreshing the cache if stale.

    If the kid is not found in the cached keyset, force a one-time refresh
    before giving up — handles Supabase key rotation without waiting for TTL.
    """
    global _jwks_keys, _jwks_fetched_at

    def _refresh() -> None:
        global _jwks_keys, _jwks_fetched_at
        resp = httpx.get(
            f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            timeout=10.0,
        )
        resp.raise_for_status()
        _jwks_keys = resp.json().get("keys", [])
        _jwks_fetched_at = time.monotonic()

    now = time.monotonic()
    with _jwks_lock:
        if not _jwks_keys or (now - _jwks_fetched_at) > _JWKS_TTL:
            _refresh()

    for key in _jwks_keys:
        if key.get("kid") == kid:
            return key

    # kid not found — force refresh once (handles key rotation mid-TTL)
    with _jwks_lock:
        _refresh()

    for key in _jwks_keys:
        if key.get("kid") == kid:
            return key

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="JWT signing key not found",
        headers={"WWW-Authenticate": "Bearer"},
    )


def verify_supabase_jwt(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token header",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    alg = header.get("alg", "HS256")
    kid = header.get("kid")
    _logger.debug("JWT verify: alg=%s kid=%s", alg, kid)

    try:
        if alg == "HS256":
            payload = jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        elif alg == "ES256":
            key_data = _get_jwks_key(kid)
            public_key = ECAlgorithm.from_jwk(json.dumps(key_data))
            payload = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                audience="authenticated",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unsupported JWT algorithm: {alg}",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except PyJWTError as exc:
        _logger.warning("JWT verification failed: %s", exc)
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
