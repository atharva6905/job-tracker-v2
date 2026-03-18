import requests

from app.utils.logging import get_logger

_logger = get_logger("keepalive")


def ping_health() -> None:
    """
    Ping the /health endpoint to prevent Supabase free tier from pausing.

    The port is always 8000 when running via Docker on DigitalOcean
    (set in Dockerfile CMD). Connection errors are logged at WARNING but
    never raised — a missed keepalive is non-critical.
    """
    try:
        requests.get("http://localhost:8000/health", timeout=5)
    except Exception as exc:
        _logger.warning(
            "Keepalive ping failed",
            extra={"error_type": type(exc).__name__},
        )
