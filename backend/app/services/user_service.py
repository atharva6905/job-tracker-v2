from sqlalchemy.orm import Session

from app.dependencies.auth import User


def get_or_create_user(db: Session, *, id: str, email: str) -> User:
    """Find a user by id or create one. This is the only place users are created."""
    # Chunk 3 replaces this with real ORM queries against the users table.
    # For now, return a stub so auth wiring can be tested end-to-end once the
    # DB exists.
    from sqlalchemy import text

    row = db.execute(
        text("SELECT id, email, created_at FROM users WHERE id = :id"),
        {"id": id},
    ).fetchone()

    if row:
        return User(id=str(row.id), email=row.email, created_at=row.created_at)

    db.execute(
        text("INSERT INTO users (id, email) VALUES (:id, :email)"),
        {"id": id, "email": email},
    )
    db.commit()

    row = db.execute(
        text("SELECT id, email, created_at FROM users WHERE id = :id"),
        {"id": id},
    ).fetchone()

    return User(id=str(row.id), email=row.email, created_at=row.created_at)
