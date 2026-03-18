import uuid as uuid_module

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_or_create_user(db: Session, *, id: str, email: str) -> User:
    """Find a user by Supabase Auth UUID or create one. Only place users are created."""
    user_id = uuid_module.UUID(id)
    user = db.scalar(select(User).where(User.id == user_id))
    if user:
        return user

    user = User(id=user_id, email=email)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
