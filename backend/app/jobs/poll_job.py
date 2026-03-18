from app.utils.logging import get_logger

_logger = get_logger("gmail_poller")


def poll_gmail_account(account_id: str) -> None:
    """
    Poll a single Gmail account for new emails.

    Stub — fully implemented in chunk 10.
    """
    _logger.info(
        "Poll job triggered",
        extra={"email_account_id": account_id, "action_taken": "poll_trigger"},
    )
