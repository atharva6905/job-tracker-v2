from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.utils.company import normalize_company_name


def find_or_create_company(
    db: Session,
    user_id: UUID,
    name: str,
    location: str | None = None,
    link: str | None = None,
) -> Company:
    normalized = normalize_company_name(name)
    company = db.scalar(
        select(Company).where(
            Company.user_id == user_id,
            Company.normalized_name == normalized,
        )
    )
    if company:
        return company
    company = Company(
        user_id=user_id,
        name=name,
        normalized_name=normalized,
        location=location,
        link=link,
    )
    db.add(company)
    db.flush()
    return company
