from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import get_current_user
from app.dependencies.rate_limit import limiter
from app.models.user import User

router = APIRouter(prefix="/extension", tags=["extension"])


@router.post("/capture", status_code=201)
@limiter.limit("60/hour")
def capture_application(
    request: Request,
    _: User = Depends(get_current_user),
):
    # Implemented in chunk 13
    raise HTTPException(status_code=501, detail="Not yet implemented")
