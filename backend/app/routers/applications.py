from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.application import Application, ApplicationStatus
from app.models.user import User
from app.schemas.applications import ApplicationCreate, ApplicationResponse, ApplicationUpdate
from app.services.application_service import apply_status_transition

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationResponse])
def list_applications(
    status: Optional[ApplicationStatus] = Query(None),
    company_id: Optional[UUID] = Query(None),
    date_applied_start: Optional[date] = Query(None),
    date_applied_end: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Application).where(Application.user_id == current_user.id)
    if status is not None:
        stmt = stmt.where(Application.status == status)
    if company_id is not None:
        stmt = stmt.where(Application.company_id == company_id)
    if date_applied_start is not None:
        stmt = stmt.where(Application.date_applied >= date_applied_start)
    if date_applied_end is not None:
        stmt = stmt.where(Application.date_applied <= date_applied_end)
    stmt = stmt.offset(skip).limit(limit)
    return db.scalars(stmt).all()


@router.post("", response_model=ApplicationResponse, status_code=201)
def create_application(
    body: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = Application(
        user_id=current_user.id,
        company_id=body.company_id,
        role=body.role,
        status=ApplicationStatus.APPLIED,
        notes=body.notes,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    return application


@router.patch("/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: UUID,
    body: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    update_data = body.model_dump(exclude_unset=True)
    if "status" in update_data:
        new_status = ApplicationStatus(update_data["status"])
        apply_status_transition(application.status, new_status, is_system_triggered=False)
        update_data["status"] = new_status
    for field, value in update_data.items():
        setattr(application, field, value)
    db.commit()
    db.refresh(application)
    return application


@router.delete("/{application_id}", status_code=204)
def delete_application(
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    db.delete(application)
    db.commit()
