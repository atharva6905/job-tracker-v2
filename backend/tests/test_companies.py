import uuid

import pytest
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.user import User


@pytest.fixture
def test_company(db: Session, test_user: User) -> Company:
    company = Company(
        user_id=test_user.id,
        name="Acme Corp",
        normalized_name="acme",
        location="New York",
        link="https://acme.com",
    )
    db.add(company)
    db.flush()
    return company


# --- List ---


def test_list_companies_empty(client, auth_headers):
    response = client.get("/companies", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_companies_returns_own(client, auth_headers, test_company):
    response = client.get("/companies", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Acme Corp"


def test_list_companies_does_not_return_other_users(
    client, auth_headers, other_auth_headers, test_company
):
    response = client.get("/companies", headers=other_auth_headers)
    assert response.status_code == 200
    assert response.json() == []


# --- Create ---


def test_create_company(client, auth_headers):
    response = client.post("/companies", json={"name": "Google"}, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Google"
    assert data["normalized_name"] == "google"


def test_create_company_with_optional_fields(client, auth_headers):
    response = client.post(
        "/companies",
        json={"name": "Stripe", "location": "San Francisco", "link": "https://stripe.com"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["location"] == "San Francisco"
    assert data["link"] == "https://stripe.com"


def test_create_company_normalizes_legal_suffix(client, auth_headers):
    response = client.post("/companies", json={"name": "Acme Inc."}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["normalized_name"] == "acme"


def test_create_company_duplicate_normalized_name_returns_409(client, auth_headers):
    client.post("/companies", json={"name": "Acme Inc."}, headers=auth_headers)
    # "Acme LLC" normalizes to the same "acme"
    response = client.post("/companies", json={"name": "Acme LLC"}, headers=auth_headers)
    assert response.status_code == 409


def test_create_company_extra_fields_rejected(client, auth_headers):
    response = client.post(
        "/companies", json={"name": "Acme", "hacked": True}, headers=auth_headers
    )
    assert response.status_code == 422


# --- Get ---


def test_get_company(client, auth_headers, test_company):
    response = client.get(f"/companies/{test_company.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Acme Corp"


def test_get_company_other_user_returns_404(client, other_auth_headers, test_company):
    response = client.get(f"/companies/{test_company.id}", headers=other_auth_headers)
    assert response.status_code == 404


def test_get_company_not_found(client, auth_headers):
    response = client.get(f"/companies/{uuid.uuid4()}", headers=auth_headers)
    assert response.status_code == 404


# --- Update ---


def test_update_company_location(client, auth_headers, test_company):
    response = client.patch(
        f"/companies/{test_company.id}",
        json={"location": "San Francisco"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location"] == "San Francisco"
    assert data["name"] == "Acme Corp"  # unchanged


def test_update_company_name_renormalizes(client, auth_headers, test_company):
    response = client.patch(
        f"/companies/{test_company.id}",
        json={"name": "Acme LLC"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Acme LLC"
    assert data["normalized_name"] == "acme"


def test_update_company_other_user_returns_404(client, other_auth_headers, test_company):
    response = client.patch(
        f"/companies/{test_company.id}",
        json={"location": "London"},
        headers=other_auth_headers,
    )
    assert response.status_code == 404


# --- Delete ---


def test_delete_company(client, auth_headers, test_company):
    response = client.delete(f"/companies/{test_company.id}", headers=auth_headers)
    assert response.status_code == 204
    # Confirm gone
    assert client.get(f"/companies/{test_company.id}", headers=auth_headers).status_code == 404


def test_delete_company_other_user_returns_404(client, other_auth_headers, test_company):
    response = client.delete(f"/companies/{test_company.id}", headers=other_auth_headers)
    assert response.status_code == 404
