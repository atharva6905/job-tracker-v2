"""
Integration tests for chunk 5 security baseline:
  - Rate limiting (60/minute on /health, IP-keyed)
  - Body size limit (1 MB)
  - Extra-field rejection via Pydantic extra='forbid'
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear in-memory rate-limit counters before each test in this module."""
    from app.dependencies.rate_limit import limiter

    limiter._storage.reset()
    yield
    limiter._storage.reset()


# ---------------------------------------------------------------------------
# Rate limit — /health is IP-keyed at 60/minute
# ---------------------------------------------------------------------------


def test_health_rate_limit_triggers_at_61():
    with TestClient(app, raise_server_exceptions=False) as client:
        for i in range(60):
            resp = client.get("/health")
            assert resp.status_code == 200, f"Request {i + 1} unexpectedly failed"

        resp = client.get("/health")
        assert resp.status_code == 429
        assert resp.json() == {"detail": "Rate limit exceeded. Try again later."}
        # Retry-After header must be present
        assert "retry-after" in {k.lower() for k in resp.headers}


# ---------------------------------------------------------------------------
# Body size limit — 1 MB cap (ContentSizeLimitMiddleware)
# ---------------------------------------------------------------------------


def test_oversized_request_returns_413():
    large_body = b"x" * 1_100_000  # 1.1 MB — exceeds 1_048_576 byte limit
    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post(
            "/applications",
            content=large_body,
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 413
    assert resp.json() == {"detail": "Request body too large"}


# ---------------------------------------------------------------------------
# Extra-field rejection — Pydantic extra='forbid' on all request schemas
# ---------------------------------------------------------------------------


def test_extra_field_in_company_create_returns_422(client, auth_headers):
    resp = client.post(
        "/companies",
        json={"name": "ACME Corp", "unexpected_field": "bad"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
