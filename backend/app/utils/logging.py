"""
Structured JSON logging utilities.

=============================================================================
LOG HYGIENE RULE: Never log raw email body content, body snippets, or any
user-authored text.
Permitted fields only: gmail_message_id, email_account_id, gemini_signal,
gemini_confidence, action_taken, timestamps, error types, user_id,
application_id.
Violating this rule is a GDPR/PIPEDA privacy exposure.
=============================================================================
"""

import logging
import sys
from logging import LoggerAdapter

from pythonjsonlogger import jsonlogger

_configured = False


class _JsonFormatter(jsonlogger.JsonFormatter):
    """JsonFormatter that renames asctime→timestamp and levelname→level."""

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        if "asctime" in log_record:
            log_record["timestamp"] = log_record.pop("asctime")
        if "levelname" in log_record:
            log_record["level"] = log_record.pop("levelname")


def _configure_root_logger() -> None:
    """
    Attach a JSON StreamHandler to the root logger.
    Idempotent — safe to call multiple times.
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    formatter = _JsonFormatter(fmt="%(asctime)s %(levelname)s %(message)s")
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    _configured = True


def get_logger(service_name: str) -> LoggerAdapter:
    """
    Return a LoggerAdapter with ``service`` pre-bound.

    Usage::

        logger = get_logger("gmail_poller")
        logger.info(
            "Poll started",
            extra={"email_account_id": str(account_id), "action_taken": "poll_start"},
        )

    The ``service`` field appears automatically in every JSON log record
    produced by this logger. Pass additional permitted fields via ``extra``.
    """
    _configure_root_logger()
    logger = logging.getLogger(service_name)
    return LoggerAdapter(logger, {"service": service_name})
