import os
from contextlib import asynccontextmanager

import sentry_sdk
from apscheduler.events import EVENT_JOB_ERROR, JobExecutionEvent
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.database import SessionLocal
from app.dependencies.rate_limit import get_ip_key, limiter, rate_limit_exceeded_handler
from app.jobs.cleanup_job import cleanup_expired_oauth_states
from app.jobs.keepalive_job import ping_health
from app.jobs.poll_job import poll_gmail_account
from app.models.email_account import EmailAccount
from app.routers import applications, auth, companies, extension, gmail, interviews
from app.scheduler import scheduler
from app.utils.logging import get_logger

load_dotenv()

_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    sentry_sdk.init(dsn=_sentry_dsn, traces_sample_rate=0.1)

_logger = get_logger("api")


def _scheduler_job_error_listener(event: JobExecutionEvent) -> None:
    """APScheduler hook — fires when a job raises an unhandled exception.

    poll_gmail_account() already catches everything internally, so this listener
    only fires when an exception escapes the job function entirely (e.g., an
    error before the try block, or a bug in the exception handler itself).
    Logs to stdout so the error is visible regardless of APScheduler's own
    logger propagation behaviour.
    """
    exc = event.exception
    _logger.error(
        "APScheduler job raised an unhandled exception",
        extra={
            "job_id": event.job_id,
            "scheduled_run_time": str(event.scheduled_run_time),
            "action_taken": "scheduler_job_error",
            "error_type": type(exc).__name__ if exc else "unknown",
        },
        exc_info=(type(exc), exc, event.traceback) if exc else False,
    )


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
    # --- Startup ---
    print("LIFESPAN STARTUP RUNNING", flush=True)
    scheduler.start()
    scheduler.add_listener(_scheduler_job_error_listener, EVENT_JOB_ERROR)

    db = SessionLocal()
    try:
        print("LIFESPAN: querying email_accounts...", flush=True)
        accounts = db.scalars(select(EmailAccount)).all()
        print(f"LIFESPAN: found {len(accounts)} email account(s)", flush=True)
        registered = 0
        for account in accounts:
            scheduler.add_job(
                poll_gmail_account,
                trigger="interval",
                minutes=15,
                id=f"poll_{account.id}",
                args=[str(account.id)],
                max_instances=1,
                replace_existing=True,
            )
            registered += 1
        print(f"LIFESPAN: registered {registered} poll job(s)", flush=True)
        _logger.info(
            "Startup poll jobs registered",
            extra={"account_count": registered, "action_taken": "startup_job_registration"},
        )
    except Exception:
        print("LIFESPAN: EXCEPTION during job registration — see logs", flush=True)
        _logger.error(
            "Failed to register poll jobs on startup — scheduler will have no poll jobs",
            exc_info=True,
            extra={"action_taken": "startup_job_registration_failed"},
        )
    finally:
        db.close()

    scheduler.add_job(
        cleanup_expired_oauth_states,
        trigger="interval",
        hours=1,
        id="cleanup_oauth_states",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        ping_health,
        trigger="interval",
        days=3,
        id="keepalive",
        max_instances=1,
        replace_existing=True,
    )

    yield

    # --- Shutdown ---
    scheduler.shutdown(wait=False)


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
            extra={
                "endpoint": request.url.path,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
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
app.include_router(gmail.router)


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
