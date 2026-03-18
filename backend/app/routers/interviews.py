from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.models.application import Application
from app.models.interview import Interview
from app.models.user import User
from app.schemas.interviews import InterviewCreate, InterviewResponse

router = APIRouter(tags=["interviews"])


@router.get("/applications/{application_id}/interviews", response_model=list[InterviewResponse])
def list_interviews(
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
    return db.scalars(
        select(Interview).where(Interview.application_id == application_id)
    ).all()


@router.post(
    "/applications/{application_id}/interviews",
    response_model=InterviewResponse,
    status_code=201,
)
def create_interview(
    application_id: UUID,
    body: InterviewCreate,
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
    interview = Interview(
        application_id=application_id,
        round_type=body.round_type,
        scheduled_at=body.scheduled_at,
        notes=body.notes,
    )
    db.add(interview)
    db.commit()
    db.refresh(interview)
    return interview
