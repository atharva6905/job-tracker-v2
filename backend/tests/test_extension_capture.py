"""Integration tests for chunk 13: POST /extension/capture"""

import uuid

import pytest
from sqlalchemy import select

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.job_description import JobDescription


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.dependencies.rate_limit import limiter

    limiter._storage.reset()
    yield
    limiter._storage.reset()


VALID_PAYLOAD = {
    "company_name": "Acme Corp",
    "role": "Software Engineer",
    "source_url": "https://boards.greenhouse.io/acme/jobs/12345",
    "job_description": "We are looking for a great engineer.",
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_capture_creates_in_progress_application(client, auth_headers, db, test_user):
    resp = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "IN_PROGRESS"
    assert "application_id" in data
    assert "company_id" in data

    app = db.scalar(
        select(Application).where(Application.id == uuid.UUID(data["application_id"]))
    )
    assert app is not None
    assert app.status == ApplicationStatus.IN_PROGRESS
    assert app.user_id == test_user.id


def test_capture_stores_source_url_on_application(client, auth_headers, db):
    resp = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201

    app = db.scalar(
        select(Application).where(Application.id == uuid.UUID(resp.json()["application_id"]))
    )
    assert app.source_url == VALID_PAYLOAD["source_url"]


def test_capture_creates_job_description(client, auth_headers, db):
    resp = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201

    app_id = uuid.UUID(resp.json()["application_id"])
    jd = db.scalar(select(JobDescription).where(JobDescription.application_id == app_id))
    assert jd is not None
    assert jd.raw_text == VALID_PAYLOAD["job_description"]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_duplicate_capture_returns_existing_application(client, auth_headers):
    resp1 = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    resp2 = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["application_id"] == resp2.json()["application_id"]


def test_duplicate_capture_updates_job_description(client, auth_headers, db):
    resp1 = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp1.status_code == 201
    app_id = uuid.UUID(resp1.json()["application_id"])

    updated_payload = {**VALID_PAYLOAD, "job_description": "Updated JD text."}
    resp2 = client.post("/extension/capture", json=updated_payload, headers=auth_headers)
    assert resp2.status_code == 201

    db.expire_all()
    jd = db.scalar(select(JobDescription).where(JobDescription.application_id == app_id))
    assert jd.raw_text == "Updated JD text."


# ---------------------------------------------------------------------------
# Company find-or-create
# ---------------------------------------------------------------------------


def test_capture_finds_existing_company_by_normalized_name(
    client, auth_headers, db, test_user
):
    # Pre-create "Google" — normalized to "google"
    existing_company = Company(
        user_id=test_user.id,
        name="Google",
        normalized_name="google",
    )
    db.add(existing_company)
    db.flush()

    # "Google LLC" normalizes to "google" — should match the existing company
    payload = {
        **VALID_PAYLOAD,
        "company_name": "Google LLC",
        "source_url": "https://myworkday.com/wday/cxs/google/googlecareers/jobs/12345",
    }
    resp = client.post("/extension/capture", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    assert resp.json()["company_id"] == str(existing_company.id)


def test_capture_creates_new_company_with_normalized_name(
    client, auth_headers, db, test_user
):
    resp = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201

    company = db.scalar(
        select(Company).where(Company.id == uuid.UUID(resp.json()["company_id"]))
    )
    assert company is not None
    assert company.user_id == test_user.id
    # "Acme Corp" → lowercase → "acme corp" → strip " corp" suffix → "acme"
    assert company.normalized_name == "acme"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_capture_company_name_too_long_returns_422(client, auth_headers):
    payload = {**VALID_PAYLOAD, "company_name": "A" * 256}
    assert client.post("/extension/capture", json=payload, headers=auth_headers).status_code == 422


def test_capture_role_too_long_returns_422(client, auth_headers):
    payload = {**VALID_PAYLOAD, "role": "R" * 256}
    assert client.post("/extension/capture", json=payload, headers=auth_headers).status_code == 422


def test_capture_source_url_too_long_returns_422(client, auth_headers):
    payload = {**VALID_PAYLOAD, "source_url": "https://example.com/" + "x" * 2048}
    assert client.post("/extension/capture", json=payload, headers=auth_headers).status_code == 422


def test_capture_job_description_too_long_returns_422(client, auth_headers):
    payload = {**VALID_PAYLOAD, "job_description": "J" * 50001}
    assert client.post("/extension/capture", json=payload, headers=auth_headers).status_code == 422


def test_capture_extra_field_returns_422(client, auth_headers):
    payload = {**VALID_PAYLOAD, "unexpected_field": "bad"}
    assert client.post("/extension/capture", json=payload, headers=auth_headers).status_code == 422


def test_capture_unauthenticated_returns_401(client):
    assert client.post("/extension/capture", json=VALID_PAYLOAD).status_code == 401


# ---------------------------------------------------------------------------
# IN_PROGRESS cannot be set via PATCH
# ---------------------------------------------------------------------------


def test_patch_cannot_set_in_progress(client, auth_headers):
    # Create an application via extension capture
    resp = client.post("/extension/capture", json=VALID_PAYLOAD, headers=auth_headers)
    assert resp.status_code == 201
    app_id = resp.json()["application_id"]

    # IN_PROGRESS is excluded from ApplicationUpdate.status Literal — Pydantic rejects with 422
    patch_resp = client.patch(
        f"/applications/{app_id}",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers,
    )
    assert patch_resp.status_code == 422


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_capture_rate_limit_at_61(client, auth_headers):
    payload = {
        "company_name": "Rate Test Co",
        "role": "Engineer",
        "source_url": "https://jobs.lever.co/ratetestco/rate-test-123",
        "job_description": "Rate limit test.",
    }
    for i in range(60):
        resp = client.post("/extension/capture", json=payload, headers=auth_headers)
        assert resp.status_code == 201, f"Request {i + 1} failed with {resp.status_code}"

    resp = client.post("/extension/capture", json=payload, headers=auth_headers)
    assert resp.status_code == 429
