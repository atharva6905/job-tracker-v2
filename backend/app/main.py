import os
from contextlib import asynccontextmanager

import sentry_sdk
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.dependencies.rate_limit import get_ip_key, limiter, rate_limit_exceeded_handler
from app.routers import applications, auth, companies, extension, interviews
from app.utils.logging import get_logger

load_dotenv()

_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1)

_logger = get_logger("api")


class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds max_size bytes."""

    def __init__(self, app, max_size: int = 1_048_576):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None and int(content_length) > self.max_size:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # scheduler.start() added in chunk 9
    yield
    # scheduler.shutdown(wait=False) added in chunk 9


debug = os.getenv("DEBUG", "false").lower() == "true"

app = FastAPI(title="job-tracker-v2", lifespan=lifespan, debug=debug)

# --- Rate limiting ---
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# --- HTTP exception handler — logs 4xx at WARNING ---
@app.exception_handler(HTTPException)
async def logged_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code >= 400:
        _logger.warning(
            "HTTP error",
            extra={"endpoint": request.url.path, "status_code": exc.status_code},
        )
    return await http_exception_handler(request, exc)


# --- Validation error handler — logs 422 at WARNING ---
@app.exception_handler(RequestValidationError)
async def logged_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    _logger.warning(
        "Request validation error",
        extra={"endpoint": request.url.path, "status_code": 422},
    )
    return JSONResponse({"detail": exc.errors()}, status_code=422)


# --- Generic exception handler (must not leak stack traces) ---
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    _logger.error(
        "Unhandled exception",
        extra={"endpoint": request.url.path, "error_type": type(exc).__name__},
        exc_info=True,
    )
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


# --- Routers ---
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(applications.router)
app.include_router(interviews.router)
app.include_router(extension.router)


# --- Health check ---
@app.get("/health")
@limiter.limit("60/minute", key_func=get_ip_key)
def health(request: Request):
    return {"status": "ok"}


# --- Middleware ---
# add_middleware() prepends — last added is outermost (runs first for requests).
#
# Execution order for incoming requests:
#   CORSMiddleware → ContentSizeLimitMiddleware → SlowAPIMiddleware → handlers

# 1. SlowAPIMiddleware — innermost, runs last
app.add_middleware(SlowAPIMiddleware)

# 2. ContentSizeLimitMiddleware — rejects oversized bodies before rate-limit logic
app.add_middleware(ContentSizeLimitMiddleware, max_size=1_048_576)

# 3. CORSMiddleware — outermost, handles OPTIONS preflight before anything else.
#    Never use allow_origins=["*"] in production.
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
extension_origin = os.getenv("EXTENSION_ORIGIN", "")
if extension_origin:
    origins.append(extension_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
