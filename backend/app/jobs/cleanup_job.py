from sqlalchemy import delete, func

from app.database import SessionLocal
from app.models.gmail_oauth_state import GmailOAuthState
from app.utils.logging import get_logger

_logger = get_logger("cleanup")


def cleanup_expired_oauth_states() -> None:
    """Delete expired gmail_oauth_states rows. Runs hourly via APScheduler."""
    db = SessionLocal()
    try:
        result = db.execute(
            delete(GmailOAuthState).where(GmailOAuthState.expires_at < func.now())
        )
        db.commit()
        _logger.debug(
            "Cleaned up expired OAuth states",
            extra={"rows_deleted": result.rowcount},
        )
    finally:
        db.close()
