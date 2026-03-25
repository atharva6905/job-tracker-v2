"""Tests for JD structuring service, capture background task, and retry endpoint."""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.job_description import JobDescription
from app.services.jd_structuring_service import (
    _normalize_work_model,
    _parse_response,
    structure_job_description,
)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    from app.dependencies.rate_limit import limiter

    limiter._storage.reset()
    yield
    limiter._storage.reset()


SAMPLE_STRUCTURED = {
    "summary": "A software engineer role at Acme.",
    "responsibilities": ["Write code", "Review PRs"],
    "required_qualifications": ["BS in CS", "2+ years Python"],
    "preferred_qualifications": ["Kubernetes experience"],
    "tech_stack": ["Python", "FastAPI", "PostgreSQL"],
    "compensation": "$120k-$150k",
    "application_deadline": "2026-04-15",
    "location": "San Francisco, CA",
    "work_model": "Hybrid",
    "company_overview": "Acme builds widgets.",
}

GEMINI_RESPONSE_TEXT = (
    '{"summary": "A software engineer role at Acme.", '
    '"responsibilities": ["Write code", "Review PRs"], '
    '"required_qualifications": ["BS in CS", "2+ years Python"], '
    '"preferred_qualifications": ["Kubernetes experience"], '
    '"tech_stack": ["Python", "FastAPI", "PostgreSQL"], '
    '"compensation": "$120k-$150k", '
    '"application_deadline": "2026-04-15", '
    '"location": "San Francisco, CA", '
    '"work_model": "Hybrid", '
    '"company_overview": "Acme builds widgets."}'
)


# ---------------------------------------------------------------------------
# Unit: _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_valid():
    result = _parse_response(GEMINI_RESPONSE_TEXT)
    assert result is not None
    assert result["summary"] == "A software engineer role at Acme."
    assert result["tech_stack"] == ["Python", "FastAPI", "PostgreSQL"]
    assert result["work_model"] == "Hybrid"


def test_parse_response_with_markdown_fences():
    text = f"```json\n{GEMINI_RESPONSE_TEXT}\n```"
    result = _parse_response(text)
    assert result is not None
    assert result["summary"] == "A software engineer role at Acme."


def test_parse_response_no_json():
    assert _parse_response("No JSON here") is None


def test_parse_response_missing_summary():
    assert _parse_response('{"responsibilities": ["test"]}') is None


def test_normalize_work_model():
    assert _normalize_work_model("Remote") == "Remote"
    assert _normalize_work_model("hybrid") == "Hybrid"
    assert _normalize_work_model("On-site") == "On-site"
    assert _normalize_work_model("onsite") == "On-site"
    assert _normalize_work_model("something else") is None
    assert _normalize_work_model(None) is None
    assert _normalize_work_model(123) is None


# ---------------------------------------------------------------------------
# Service: structure_job_description
# ---------------------------------------------------------------------------


def test_structure_jd_success(db, test_user):
    company = Company(user_id=test_user.id, name="Acme", normalized_name="acme")
    db.add(company)
    db.flush()
    app = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Engineer",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()
    jd = JobDescription(application_id=app.id, raw_text="Full JD text here.")
    db.add(jd)
    db.flush()

    mock_response = MagicMock()
    mock_response.text = GEMINI_RESPONSE_TEXT

    with patch("app.services.jd_structuring_service.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        structure_job_description(db, str(jd.id))

    db.expire_all()
    jd_after = db.get(JobDescription, jd.id)
    assert jd_after.structured_jd is not None
    assert jd_after.structured_jd["summary"] == "A software engineer role at Acme."
    assert jd_after.structured_jd["tech_stack"] == ["Python", "FastAPI", "PostgreSQL"]


def test_structure_jd_idempotent(db, test_user):
    company = Company(user_id=test_user.id, name="Acme", normalized_name="acme")
    db.add(company)
    db.flush()
    app = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Engineer",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()
    jd = JobDescription(
        application_id=app.id,
        raw_text="Full JD text here.",
        structured_jd=SAMPLE_STRUCTURED,
    )
    db.add(jd)
    db.flush()

    with patch("app.services.jd_structuring_service.genai") as mock_genai:
        structure_job_description(db, str(jd.id))
        # Gemini should NOT be called — already populated
        mock_genai.Client.assert_not_called()


def test_structure_jd_not_found(db):
    # Should not raise — just log and return
    with patch("app.services.jd_structuring_service.genai"):
        structure_job_description(db, str(uuid.uuid4()))


def test_structure_jd_parse_failure(db, test_user):
    company = Company(user_id=test_user.id, name="Acme", normalized_name="acme")
    db.add(company)
    db.flush()
    app = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Engineer",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()
    jd = JobDescription(application_id=app.id, raw_text="Full JD text here.")
    db.add(jd)
    db.flush()

    mock_response = MagicMock()
    mock_response.text = "Not valid JSON at all"

    with patch("app.services.jd_structuring_service.genai") as mock_genai:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_genai.Client.return_value = mock_client

        structure_job_description(db, str(jd.id))

    db.expire_all()
    jd_after = db.get(JobDescription, jd.id)
    assert jd_after.structured_jd is None  # left null on failure


# ---------------------------------------------------------------------------
# Integration: POST /applications/{id}/structure-jd
# ---------------------------------------------------------------------------


def test_structure_jd_endpoint_returns_202(client, auth_headers, db, test_user):
    company = Company(user_id=test_user.id, name="Acme", normalized_name="acme")
    db.add(company)
    db.flush()
    app = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Engineer",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()
    jd = JobDescription(application_id=app.id, raw_text="JD text.")
    db.add(jd)
    db.flush()

    with patch("app.routers.applications.structure_job_description"):
        resp = client.post(
            f"/applications/{app.id}/structure-jd",
            headers=auth_headers,
        )
    assert resp.status_code == 202


def test_structure_jd_endpoint_404_no_application(client, auth_headers):
    resp = client.post(
        f"/applications/{uuid.uuid4()}/structure-jd",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_structure_jd_endpoint_404_no_jd(client, auth_headers, db, test_user):
    company = Company(user_id=test_user.id, name="Acme", normalized_name="acme")
    db.add(company)
    db.flush()
    app = Application(
        user_id=test_user.id,
        company_id=company.id,
        role="Engineer",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()

    resp = client.post(
        f"/applications/{app.id}/structure-jd",
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_structure_jd_endpoint_unauthenticated(client):
    resp = client.post(f"/applications/{uuid.uuid4()}/structure-jd")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Integration: /extension/capture queues background task
# ---------------------------------------------------------------------------


def test_capture_queues_structuring_background_task(client, auth_headers, db):
    payload = {
        "company_name": "Acme Corp",
        "role": "Software Engineer",
        "source_url": "https://boards.greenhouse.io/acme/jobs/99999",
        "job_description": "We are looking for a great engineer.",
    }
    with patch("app.routers.extension.structure_job_description") as mock_struct:
        resp = client.post("/extension/capture", json=payload, headers=auth_headers)
        assert resp.status_code == 201
        assert resp.json()["message"] == "created"
        # Background task should have been called with the JD id
        mock_struct.assert_called_once()
        call_args = mock_struct.call_args
        # First arg is db session, second is jd_id string
        assert isinstance(call_args[0][1], str)


def test_capture_idempotent_does_not_queue_structuring(client, auth_headers, db):
    payload = {
        "company_name": "Acme Corp",
        "role": "Software Engineer",
        "source_url": "https://boards.greenhouse.io/acme/jobs/88888",
        "job_description": "We are looking for a great engineer.",
    }
    with patch("app.routers.extension.structure_job_description") as mock_struct:
        # First call — creates
        resp1 = client.post("/extension/capture", json=payload, headers=auth_headers)
        assert resp1.json()["message"] == "created"
        assert mock_struct.call_count == 1

        # Second call — idempotent (existing)
        resp2 = client.post("/extension/capture", json=payload, headers=auth_headers)
        assert resp2.json()["message"] == "existing"
        # Should NOT queue structuring again
        assert mock_struct.call_count == 1
