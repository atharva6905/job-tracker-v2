from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from sqlalchemy import asc, nullslast, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import limiter
from app.models.application import Application, ApplicationStatus
from app.models.job_description import JobDescription
from app.models.raw_email import RawEmail
from app.models.user import User
from app.schemas.applications import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
    JobDescriptionResponse,
)
from app.schemas.raw_email import RawEmailResponse
from app.services.application_service import apply_status_transition
from app.services.jd_structuring_service import structure_job_description

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationResponse])
@limiter.limit("60/minute")
def list_applications(
    request: Request,
    status: Optional[ApplicationStatus] = Query(None),
    company_id: Optional[UUID] = Query(None),
    date_applied_start: Optional[date] = Query(None),
    date_applied_end: Optional[date] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Application).where(
        Application.user_id == current_user.id,
        Application.deleted_at.is_(None),
    )
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
@limiter.limit("60/minute")
def create_application(
    request: Request,
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
@limiter.limit("60/minute")
def get_application(
    request: Request,
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    return application


@router.patch("/{application_id}", response_model=ApplicationResponse)
@limiter.limit("60/minute")
def update_application(
    request: Request,
    application_id: UUID,
    body: ApplicationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
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


@router.get("/{application_id}/job-description", response_model=JobDescriptionResponse | None)
@limiter.limit("60/minute")
def get_job_description(
    request: Request,
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    jd = db.scalar(
        select(JobDescription).where(
            JobDescription.application_id == application_id
        )
    )
    if not jd:
        return None
    return jd


@router.get("/{application_id}/emails", response_model=list[RawEmailResponse])
@limiter.limit("60/minute")
def get_application_emails(
    request: Request,
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    emails = db.scalars(
        select(RawEmail)
        .where(RawEmail.linked_application_id == application_id)
        .order_by(nullslast(asc(RawEmail.received_at)))
    ).all()
    return emails


@router.post("/{application_id}/structure-jd", status_code=202)
@limiter.limit("10/minute")
def structure_jd(
    request: Request,
    application_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    jd = db.scalar(
        select(JobDescription).where(
            JobDescription.application_id == application_id
        )
    )
    if not jd:
        raise HTTPException(status_code=404, detail="No job description found")
    background_tasks.add_task(structure_job_description, db, str(jd.id))
    return {"detail": "Structuring queued"}


@router.delete("/{application_id}", status_code=204)
@limiter.limit("60/minute")
def delete_application(
    request: Request,
    application_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.id == application_id,
            Application.user_id == current_user.id,
            Application.deleted_at.is_(None),
        )
    )
    if not application:
        raise HTTPException(status_code=404)
    application.deleted_at = datetime.now(timezone.utc)
    db.commit()
