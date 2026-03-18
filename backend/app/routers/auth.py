from fastapi import APIRouter, Depends

from app.dependencies.auth import User, get_current_user
from app.schemas.user import UserResponse

router = APIRouter()


@router.get("/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.get("/users/me/export")
def export_user_data(_: User = Depends(get_current_user)):
    from fastapi import HTTPException
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/users/me")
def delete_user(_: User = Depends(get_current_user)):
    from fastapi import HTTPException
    raise HTTPException(status_code=501, detail="Not yet implemented")
