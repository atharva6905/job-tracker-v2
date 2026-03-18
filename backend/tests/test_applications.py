import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.user import User
from app.services.application_service import apply_status_transition


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
        status=ApplicationStatus.APPLIED,
    )
    db.add(app)
    db.flush()
    return app


@pytest.fixture
def in_progress_application(db: Session, test_user: User, test_company: Company) -> Application:
    app = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Data Scientist",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(app)
    db.flush()
    return app


# --- List ---


def test_list_applications_empty(client, auth_headers):
    response = client.get("/applications", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_applications_returns_own(client, auth_headers, test_application):
    response = client.get("/applications", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_applications_filter_by_status(
    client, auth_headers, test_application, db, test_user, test_company
):
    in_progress = Application(
        user_id=test_user.id,
        company_id=test_company.id,
        role="Other Role",
        status=ApplicationStatus.IN_PROGRESS,
    )
    db.add(in_progress)
    db.flush()

    response = client.get("/applications?status=APPLIED", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["status"] == "APPLIED"


def test_list_applications_filter_by_company(
    client, auth_headers, test_application, db, test_user
):
    other_company = Company(user_id=test_user.id, name="Other Co", normalized_name="other")
    db.add(other_company)
    db.flush()
    other_app = Application(
        user_id=test_user.id,
        company_id=other_company.id,
        role="PM",
        status=ApplicationStatus.APPLIED,
    )
    db.add(other_app)
    db.flush()

    response = client.get(
        f"/applications?company_id={test_application.company_id}", headers=auth_headers
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_list_applications_pagination(client, auth_headers, db, test_user, test_company):
    for i in range(5):
        app = Application(
            user_id=test_user.id,
            company_id=test_company.id,
            role=f"Role {i}",
            status=ApplicationStatus.APPLIED,
        )
        db.add(app)
    db.flush()

    r1 = client.get("/applications?skip=0&limit=3", headers=auth_headers)
    assert r1.status_code == 200
    assert len(r1.json()) == 3

    r2 = client.get("/applications?skip=3&limit=3", headers=auth_headers)
    assert r2.status_code == 200
    assert len(r2.json()) == 2


# --- Create ---


def test_create_application(client, auth_headers, test_company):
    response = client.post(
        "/applications",
        json={"company_id": str(test_company.id), "role": "Engineer"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "Engineer"
    assert data["status"] == "APPLIED"


def test_create_application_with_notes(client, auth_headers, test_company):
    response = client.post(
        "/applications",
        json={"company_id": str(test_company.id), "role": "PM", "notes": "Referral from Jane"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["notes"] == "Referral from Jane"


def test_create_application_extra_fields_rejected(client, auth_headers, test_company):
    response = client.post(
        "/applications",
        json={"company_id": str(test_company.id), "role": "Engineer", "hacked": True},
        headers=auth_headers,
    )
    assert response.status_code == 422


# --- Get ---


def test_get_application(client, auth_headers, test_application):
    response = client.get(f"/applications/{test_application.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["role"] == "Software Engineer"


def test_get_application_other_user_returns_404(
    client, other_auth_headers, test_application
):
    response = client.get(f"/applications/{test_application.id}", headers=other_auth_headers)
    assert response.status_code == 404


def test_get_application_not_found(client, auth_headers):
    response = client.get(f"/applications/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


# --- Update / transitions ---


def test_patch_application_role(client, auth_headers, test_application):
    response = client.patch(
        f"/applications/{test_application.id}",
        json={"role": "Senior Engineer"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == "Senior Engineer"


def test_patch_application_status_applied_to_interview(client, auth_headers, test_application):
    response = client.patch(
        f"/applications/{test_application.id}",
        json={"status": "INTERVIEW"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "INTERVIEW"


def test_patch_application_manual_override_bypasses_transition_rules(
    client, auth_headers, in_progress_application
):
    # IN_PROGRESS → OFFER directly — manual override bypasses rules
    response = client.patch(
        f"/applications/{in_progress_application.id}",
        json={"status": "OFFER"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "OFFER"


def test_patch_application_in_progress_status_rejected(client, auth_headers, test_application):
    # IN_PROGRESS is excluded from ApplicationUpdate.status Literal — Pydantic rejects it
    response = client.patch(
        f"/applications/{test_application.id}",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_patch_application_partial_update_preserves_other_fields(
    client, auth_headers, test_application
):
    response = client.patch(
        f"/applications/{test_application.id}",
        json={"notes": "Follow up Monday"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["notes"] == "Follow up Monday"
    assert data["role"] == "Software Engineer"  # unchanged
    assert data["status"] == "APPLIED"  # unchanged


def test_patch_application_other_user_returns_404(
    client, other_auth_headers, test_application
):
    response = client.patch(
        f"/applications/{test_application.id}",
        json={"role": "Hacked"},
        headers=other_auth_headers,
    )
    assert response.status_code == 404


# --- Service-level transition tests ---


def test_apply_status_transition_valid_system_triggered():
    # Should not raise
    apply_status_transition(
        ApplicationStatus.IN_PROGRESS, ApplicationStatus.APPLIED, is_system_triggered=True
    )


def test_apply_status_transition_invalid_system_triggered_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        apply_status_transition(
            ApplicationStatus.OFFER, ApplicationStatus.INTERVIEW, is_system_triggered=True
        )
    assert exc_info.value.status_code == 400


def test_apply_status_transition_terminal_offer_raises():
    with pytest.raises(HTTPException) as exc_info:
        apply_status_transition(
            ApplicationStatus.OFFER, ApplicationStatus.APPLIED, is_system_triggered=True
        )
    assert exc_info.value.status_code == 400


def test_apply_status_transition_terminal_rejected_raises():
    with pytest.raises(HTTPException) as exc_info:
        apply_status_transition(
            ApplicationStatus.REJECTED, ApplicationStatus.INTERVIEW, is_system_triggered=True
        )
    assert exc_info.value.status_code == 400


def test_apply_status_transition_manual_allows_any_non_in_progress():
    # Manual override: any target except IN_PROGRESS is fine
    apply_status_transition(
        ApplicationStatus.OFFER, ApplicationStatus.INTERVIEW, is_system_triggered=False
    )


def test_apply_status_transition_manual_in_progress_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        apply_status_transition(
            ApplicationStatus.APPLIED, ApplicationStatus.IN_PROGRESS, is_system_triggered=False
        )
    assert exc_info.value.status_code == 400


# --- Delete ---


def test_delete_application(client, auth_headers, test_application):
    response = client.delete(f"/applications/{test_application.id}", headers=auth_headers)
    assert response.status_code == 204
    assert (
        client.get(f"/applications/{test_application.id}", headers=auth_headers).status_code
        == 404
    )


def test_delete_application_other_user_returns_404(
    client, other_auth_headers, test_application
):
    response = client.delete(
        f"/applications/{test_application.id}", headers=other_auth_headers
    )
    assert response.status_code == 404
