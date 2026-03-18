from fastapi import APIRouter, Depends, HTTPException, Request

from app.dependencies.auth import User, get_current_user
from app.dependencies.rate_limit import limiter
from app.schemas.user import UserResponse
from app.utils.logging import get_logger

router = APIRouter()
_logger = get_logger("auth")


@router.get("/auth/me", response_model=UserResponse)
@limiter.limit("60/minute")
def get_me(request: Request, current_user: User = Depends(get_current_user)) -> User:
    _logger.debug("Auth successful", extra={"user_id": str(current_user.id)})
    return current_user


@router.get("/users/me/export")
@limiter.limit("5/hour")
def export_user_data(request: Request, _: User = Depends(get_current_user)):
    # Implemented in chunk 8
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/users/me")
@limiter.limit("3/hour")
def delete_user(request: Request, _: User = Depends(get_current_user)):
    # Implemented in chunk 8
    raise HTTPException(status_code=501, detail="Not yet implemented")
