import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.interview import Interview, RoundType
from app.models.user import User


@pytest.fixture
def test_company(db: Session, test_user: User) -> Company:
    company = Company(
        user_id=test_user.id,
        name="Acme Corp",
        normalized_name="acme",
    )
    db.add(company)
    db.flush()
    return company


@pytest.fixture
def test_application(db: Session, test_user: User, test_company: Company) -> Application:
    app = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Software Engineer",
        status=ApplicationStatus.INTERVIEW,
    )
    db.add(app)
    db.flush()
    return app


# --- Create ---


def test_create_interview(client, auth_headers, test_application):
    response = client.post(
        f"/applications/{test_application.id}/interviews",
        json={"round_type": "TECHNICAL"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["round_type"] == "TECHNICAL"
    assert data["application_id"] == str(test_application.id)
    assert data["outcome"] is None
    assert data["scheduled_at"] is None


def test_create_interview_with_all_fields(client, auth_headers, test_application):
    response = client.post(
        f"/applications/{test_application.id}/interviews",
        json={
            "round_type": "PHONE",
            "scheduled_at": "2026-03-20T10:00:00Z",
            "notes": "First round screen",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["round_type"] == "PHONE"
    assert data["notes"] == "First round screen"
    assert data["scheduled_at"] is not None


def test_create_interview_extra_fields_rejected(client, auth_headers, test_application):
    response = client.post(
        f"/applications/{test_application.id}/interviews",
        json={"round_type": "TECHNICAL", "hacked": True},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_create_interview_application_not_found(client, auth_headers):
    response = client.post(
        f"/applications/{uuid.uuid4()}/interviews",
        json={"round_type": "TECHNICAL"},
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_create_interview_other_user_application_returns_404(
    client, other_auth_headers, test_application
):
    response = client.post(
        f"/applications/{test_application.id}/interviews",
        json={"round_type": "BEHAVIORAL"},
        headers=other_auth_headers,
    )
    assert response.status_code == 404


# --- List ---


def test_list_interviews_empty(client, auth_headers, test_application):
    response = client.get(
        f"/applications/{test_application.id}/interviews", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json() == []


def test_list_interviews(client, auth_headers, test_application, db):
    interview = Interview(
        application_id=test_application.id,
        round_type=RoundType.PHONE,
    )
    db.add(interview)
    db.flush()

    response = client.get(
        f"/applications/{test_application.id}/interviews", headers=auth_headers
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["round_type"] == "PHONE"


def test_list_interviews_multiple(client, auth_headers, test_application, db):
    for round_type in [RoundType.PHONE, RoundType.TECHNICAL, RoundType.FINAL]:
        db.add(Interview(application_id=test_application.id, round_type=round_type))
    db.flush()

    response = client.get(
        f"/applications/{test_application.id}/interviews", headers=auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 3


def test_list_interviews_application_not_found(client, auth_headers):
    response = client.get(f"/applications/{uuid.uuid4()}/interviews", headers=auth_headers)
    assert response.status_code == 404


def test_list_interviews_other_user_returns_404(
    client, other_auth_headers, test_application
):
    response = client.get(
        f"/applications/{test_application.id}/interviews", headers=other_auth_headers
    )
    assert response.status_code == 404


def test_interviews_are_scoped_to_application(
    client, auth_headers, test_user, test_company, db
):
    # Two applications, each with one interview
    app1 = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Role A",
        status=ApplicationStatus.INTERVIEW,
    )
    app2 = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Role B",
        status=ApplicationStatus.INTERVIEW,
    )
    db.add_all([app1, app2])
    db.flush()
    db.add(Interview(application_id=app1.id, round_type=RoundType.PHONE))
    db.add(Interview(application_id=app2.id, round_type=RoundType.TECHNICAL))
    db.flush()

    r1 = client.get(f"/applications/{app1.id}/interviews", headers=auth_headers)
    assert len(r1.json()) == 1
    assert r1.json()[0]["round_type"] == "PHONE"

    r2 = client.get(f"/applications/{app2.id}/interviews", headers=auth_headers)
    assert len(r2.json()) == 1
    assert r2.json()[0]["round_type"] == "TECHNICAL"
