import os

from fastapi import Request
from jose import JWTError, jwt
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

_SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")


def get_ip_key(request: Request) -> str:
    """Rate-limit key based on client IP — use for public endpoints."""
    return request.client.host


def get_user_key(request: Request) -> str:
    """
    Rate-limit key based on verified JWT user ID.
    Falls back to client IP if no valid JWT is present.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            payload = jwt.decode(
                token,
                _SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
                options={"verify_exp": True},
            )
            return f"user:{payload['sub']}"
    except (JWTError, Exception):
        pass
    return request.client.host


# Single shared Limiter instance — imported by all routers and main.py.
# Default key function is user-keyed; override per-endpoint for IP-keyed routes.
limiter = Limiter(key_func=get_user_key)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a consistent 429 JSON body with a Retry-After header."""
    return JSONResponse(
        {"detail": "Rate limit exceeded. Try again later."},
        status_code=429,
        headers={"Retry-After": str(getattr(exc, "retry_after", 60))},
    )
