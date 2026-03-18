from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import limiter
from app.models.company import Company
from app.models.user import User
from app.schemas.companies import CompanyCreate, CompanyResponse, CompanyUpdate
from app.utils.company import normalize_company_name

router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("", response_model=list[CompanyResponse])
@limiter.limit("60/minute")
def list_companies(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.scalars(
        select(Company).where(Company.user_id == current_user.id)
    ).all()


@router.post("", response_model=CompanyResponse, status_code=201)
@limiter.limit("60/minute")
def create_company(
    request: Request,
    body: CompanyCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    normalized = normalize_company_name(body.name)
    existing = db.scalar(
        select(Company).where(
            Company.user_id == current_user.id,
            Company.normalized_name == normalized,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Company already exists")
    company = Company(
        user_id=current_user.id,
        name=body.name,
        normalized_name=normalized,
        location=body.location,
        link=body.link,
    )
    db.add(company)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Company already exists")
    db.refresh(company)
    return company


@router.get("/{company_id}", response_model=CompanyResponse)
@limiter.limit("60/minute")
def get_company(
    request: Request,
    company_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.user_id == current_user.id,
        )
    )
    if not company:
        raise HTTPException(status_code=404)
    return company


@router.patch("/{company_id}", response_model=CompanyResponse)
@limiter.limit("60/minute")
def update_company(
    request: Request,
    company_id: UUID,
    body: CompanyUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.user_id == current_user.id,
        )
    )
    if not company:
        raise HTTPException(status_code=404)
    update_data = body.model_dump(exclude_unset=True)
    if "name" in update_data:
        update_data["normalized_name"] = normalize_company_name(update_data["name"])
    for field, value in update_data.items():
        setattr(company, field, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Company already exists")
    db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=204)
@limiter.limit("60/minute")
def delete_company(
    request: Request,
    company_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.user_id == current_user.id,
        )
    )
    if not company:
        raise HTTPException(status_code=404)
    db.delete(company)
    db.commit()
