"""Tests for structured JSON logging utilities."""

import io
import json
import logging
import uuid

import pytest
from pythonjsonlogger import jsonlogger

from app.utils.logging import _JsonFormatter, get_logger


def _make_captured_logger(name: str | None = None) -> tuple[logging.Logger, io.StringIO]:
    """
    Return an isolated (non-propagating) Logger wired to a StringIO stream,
    formatted with _JsonFormatter.  Caller is responsible for removing the
    handler after use.
    """
    name = name or f"test_{uuid.uuid4().hex}"
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter(fmt="%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger(name)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


def test_json_formatter_outputs_valid_json():
    """JSON formatter must produce parseable JSON with the expected fields."""
    logger, stream = _make_captured_logger()
    try:
        logger.info("hello structured world")
        output = stream.getvalue().strip()
        assert output, "Expected log output but stream is empty"
        parsed = json.loads(output)  # raises json.JSONDecodeError if invalid
        assert parsed["message"] == "hello structured world"
    finally:
        logger.handlers.clear()


def test_json_formatter_renames_timestamp_and_level():
    """asctime must be renamed to 'timestamp' and levelname to 'level'."""
    logger, stream = _make_captured_logger()
    try:
        logger.warning("rename check")
        parsed = json.loads(stream.getvalue().strip())
        assert "timestamp" in parsed, "Expected 'timestamp' key (renamed from asctime)"
        assert "level" in parsed, "Expected 'level' key (renamed from levelname)"
        assert "asctime" not in parsed
        assert "levelname" not in parsed
    finally:
        logger.handlers.clear()


def test_json_formatter_includes_extra_fields():
    """Extra kwargs passed at call time must appear in the JSON output."""
    logger, stream = _make_captured_logger()
    try:
        logger.info(
            "extra fields",
            extra={"action_taken": "poll_start", "email_account_id": "abc-123"},
        )
        parsed = json.loads(stream.getvalue().strip())
        assert parsed["action_taken"] == "poll_start"
        assert parsed["email_account_id"] == "abc-123"
    finally:
        logger.handlers.clear()


def test_get_logger_returns_logger_adapter():
    """get_logger() must return a LoggerAdapter instance."""
    logger = get_logger("test_service")
    assert isinstance(logger, logging.LoggerAdapter)


def test_get_logger_binds_service_field():
    """get_logger() must pre-bind the service name as 'service' in extra."""
    service = f"svc_{uuid.uuid4().hex}"
    logger = get_logger(service)
    assert logger.extra["service"] == service


def test_get_logger_service_appears_in_output():
    """The service field must appear in the JSON output of every log record."""
    service = f"svc_{uuid.uuid4().hex}"
    adapter = get_logger(service)

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter(fmt="%(asctime)s %(levelname)s %(message)s"))
    adapter.logger.addHandler(handler)
    adapter.logger.setLevel(logging.DEBUG)
    adapter.logger.propagate = False

    try:
        adapter.info("service binding check")
        parsed = json.loads(stream.getvalue().strip())
        assert parsed["service"] == service
    finally:
        adapter.logger.handlers.clear()


def test_no_forbidden_fields_in_default_log_output():
    """
    A default log call must not produce records containing PII field names.
    Forbidden: body, snippet, email_body, raw_text.
    This guards against accidentally injecting these fields via LoggerAdapter extras.
    """
    forbidden = {"body", "snippet", "email_body", "raw_text"}
    adapter = get_logger(f"hygiene_{uuid.uuid4().hex}")

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonFormatter(fmt="%(asctime)s %(levelname)s %(message)s"))
    adapter.logger.addHandler(handler)
    adapter.logger.setLevel(logging.DEBUG)
    adapter.logger.propagate = False

    try:
        # Log with permitted fields only — the forbidden names must not appear
        adapter.info(
            "normal log",
            extra={
                "action_taken": "poll_start",
                "email_account_id": "acct-1",
                "user_id": "user-1",
            },
        )
        parsed = json.loads(stream.getvalue().strip())
        found = forbidden & set(parsed.keys())
        assert not found, f"Forbidden PII fields found in log output: {found}"
    finally:
        adapter.logger.handlers.clear()
