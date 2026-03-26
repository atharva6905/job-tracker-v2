import csv
import io
import uuid
from unittest.mock import patch

from sqlalchemy.orm import Session

from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.email_account import EmailAccount
from app.utils.encryption import encrypt_token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_company(db: Session, user_id: uuid.UUID) -> Company:
    company = Company(
        user_id=user_id,
        name="Acme Corp",
        normalized_name="acme corp",
    )
    db.add(company)
    db.flush()
    return company


def _make_application(
    db: Session, user_id: uuid.UUID, company_id: uuid.UUID
) -> Application:
    app = Application(
        user_id=user_id,
        company_id=company_id,
        role="Engineer",
        status=ApplicationStatus.APPLIED,
    )
    db.add(app)
    db.flush()
    return app


def _make_email_account(db: Session, user_id: uuid.UUID) -> EmailAccount:
    account = EmailAccount(
        user_id=user_id,
        email="test@gmail.com",
        access_token=encrypt_token("access"),
        refresh_token=encrypt_token("refresh"),
    )
    db.add(account)
    db.flush()
    return account


def _parse_csv(resp) -> list[dict]:
    reader = csv.DictReader(io.StringIO(resp.text))
    return list(reader)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_export_returns_csv_with_correct_headers(client, auth_headers):
    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "job-tracker-export.csv" in resp.headers["content-disposition"]
    rows = _parse_csv(resp)
    assert isinstance(rows, list)


def test_export_empty_user_returns_header_only(client, auth_headers):
    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    rows = _parse_csv(resp)
    assert len(rows) == 0


def test_export_includes_application_data(client, auth_headers, test_user, db: Session):
    company = _make_company(db, test_user.id)
    _make_application(db, test_user.id, company.id)

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200
    rows = _parse_csv(resp)

    assert len(rows) == 1
    assert rows[0]["company"] == "Acme Corp"
    assert rows[0]["role"] == "Engineer"
    assert rows[0]["status"] == "APPLIED"


def test_export_csv_columns(client, auth_headers, test_user, db: Session):
    company = _make_company(db, test_user.id)
    _make_application(db, test_user.id, company.id)

    resp = client.get("/users/me/export", headers=auth_headers)
    rows = _parse_csv(resp)

    expected_cols = {"company", "role", "status", "date_applied", "created_at", "source_url", "notes"}
    assert set(rows[0].keys()) == expected_cols


def test_export_no_tokens_in_response(client, auth_headers, test_user, db: Session):
    _make_email_account(db, test_user.id)

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 200

    response_text = resp.text
    assert "access_token" not in response_text
    assert "refresh_token" not in response_text


def test_export_after_delete_returns_401(client, auth_headers):
    with patch("app.routers.auth.scheduler"):
        del_resp = client.delete("/users/me", headers=auth_headers)
    assert del_resp.status_code == 204

    resp = client.get("/users/me/export", headers=auth_headers)
    assert resp.status_code == 401


def test_export_unauthenticated_returns_401(client):
    resp = client.get("/users/me/export")
    assert resp.status_code == 401
