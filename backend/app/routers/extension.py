from datetime import date, datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import limiter
from app.models.application import Application, ApplicationStatus
from app.models.job_description import JobDescription
from app.models.user import User
from app.schemas.extension import (
    ExtensionAppliedRequest,
    ExtensionCaptureRequest,
    ExtensionCaptureResponse,
)
from app.services.company_service import find_or_create_company
from app.services.email_application_service import replay_matched_emails
from app.services.jd_structuring_service import structure_job_description
from app.utils.workday import extract_workday_tenant

router = APIRouter(prefix="/extension", tags=["extension"])


@router.post("/capture", response_model=ExtensionCaptureResponse, status_code=201)
@limiter.limit("60/hour")
def capture_application(
    request: Request,
    body: ExtensionCaptureRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    company = find_or_create_company(db, current_user.id, body.company_name)

    # Dedup: if an IN_PROGRESS application exists for this (user, source_url),
    # update its job description and return it — don't create a duplicate.
    existing = db.scalar(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.source_url == body.source_url,
            Application.status == ApplicationStatus.IN_PROGRESS,
        )
    )

    if existing:
        existing.company_id = company.id
        existing.role = body.role
        existing.ats_job_id = body.ats_job_id
        existing.workday_tenant = extract_workday_tenant(body.source_url)
        jd = db.scalar(
            select(JobDescription).where(JobDescription.application_id == existing.id)
        )
        if jd:
            jd.raw_text = body.job_description
            jd.captured_at = datetime.now(timezone.utc)
        else:
            db.add(JobDescription(application_id=existing.id, raw_text=body.job_description))
        db.commit()
        return ExtensionCaptureResponse(
            application_id=existing.id,
            company_id=existing.company_id,
            status=existing.status.value,
            message="existing",
        )

    application = Application(
        user_id=current_user.id,
        company_id=company.id,
        role=body.role,
        status=ApplicationStatus.IN_PROGRESS,
        source_url=body.source_url,
        ats_job_id=body.ats_job_id,
        workday_tenant=extract_workday_tenant(body.source_url),
    )
    db.add(application)
    db.flush()
    jd = JobDescription(application_id=application.id, raw_text=body.job_description)
    db.add(jd)
    db.commit()
    db.refresh(jd)
    background_tasks.add_task(structure_job_description, db, str(jd.id))
    replay_matched_emails(db, application)
    db.refresh(application)
    return ExtensionCaptureResponse(
        application_id=application.id,
        company_id=application.company_id,
        status=application.status.value,
        message="created",
    )


@router.post("/applied", response_model=ExtensionCaptureResponse, status_code=200)
@limiter.limit("10/minute")
def mark_applied(
    request: Request,
    body: ExtensionAppliedRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(Application).where(
            Application.user_id == current_user.id,
            Application.source_url == body.source_url,
            Application.status == ApplicationStatus.IN_PROGRESS,
        )
    )
    if not application:
        raise HTTPException(status_code=404)

    application.status = ApplicationStatus.APPLIED
    application.date_applied = date.today()
    db.commit()

    return ExtensionCaptureResponse(
        application_id=application.id,
        company_id=application.company_id,
        status=application.status.value,
        message="applied",
    )
