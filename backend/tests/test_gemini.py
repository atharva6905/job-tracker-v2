"""Integration tests for Gemini classification service (chunk 11)."""
import logging
from unittest.mock import MagicMock, patch

from google.genai import errors as genai_errors

from app.services.gemini_service import GeminiClassificationResult, classify_email


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_429() -> genai_errors.ClientError:
    """Build a ClientError that represents a 429 rate-limit response."""
    return genai_errors.ClientError(
        429,
        {"error": {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}},
        None,
    )


def _mock_response(json_text: str) -> MagicMock:
    """Build a mock Gemini response with the given text."""
    response = MagicMock()
    response.text = json_text
    return response


def _build_client_mock(side_effect=None, return_value=None) -> MagicMock:
    """
    Return a mock genai.Client instance whose models.generate_content is
    pre-configured with either side_effect or return_value.
    """
    client = MagicMock()
    if side_effect is not None:
        client.models.generate_content.side_effect = side_effect
    elif return_value is not None:
        client.models.generate_content.return_value = return_value
    return client


def _run_classify(
    mock_client,
    subject="Subject",
    sender="hr@company.com",
    body="snippet",
) -> GeminiClassificationResult:
    """Call classify_email with mocked genai.Client."""
    with patch("app.services.gemini_service.genai.Client", return_value=mock_client), \
         patch("app.services.gemini_service.time.sleep"), \
         patch("app.services.gemini_service.random.uniform", return_value=0.0):
        return classify_email(subject, sender, body)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestClassifyEmail:
    def test_applied_high_confidence_returns_applied(self):
        """APPLIED signal with confidence >= 0.75 is returned unchanged."""
        client = _build_client_mock(
            return_value=_mock_response(
                '{"company": "Acme Corp", "role": "SWE", "signal": "APPLIED", "confidence": 0.9}'
            )
        )

        result = _run_classify(client)

        assert result.signal == "APPLIED"
        assert result.confidence == 0.9
        assert result.company == "Acme Corp"
        assert result.role == "SWE"

    def test_applied_low_confidence_returns_below_threshold(self):
        """APPLIED signal with confidence < 0.75 is overwritten with BELOW_THRESHOLD."""
        client = _build_client_mock(
            return_value=_mock_response(
                '{"company": "Acme Corp", "role": "SWE", "signal": "APPLIED", "confidence": 0.6}'
            )
        )

        result = _run_classify(client)

        assert result.signal == "BELOW_THRESHOLD"
        # Original confidence is preserved — not zeroed out
        assert result.confidence == 0.6

    def test_malformed_json_returns_parse_error(self):
        """A response that cannot be parsed as JSON returns PARSE_ERROR."""
        client = _build_client_mock(
            return_value=_mock_response("not valid json at all")
        )

        result = _run_classify(client)

        assert result.signal == "PARSE_ERROR"
        assert result.confidence == 0.0
        assert result.company is None
        assert result.role is None

    def test_single_429_then_success_returns_applied(self):
        """429 on first call triggers a retry; second call succeeds."""
        success = _mock_response(
            '{"company": "Acme", "role": "SWE", "signal": "APPLIED", "confidence": 0.95}'
        )
        client = _build_client_mock(side_effect=[_make_429(), success])

        with patch("app.services.gemini_service.genai.Client", return_value=client), \
             patch("app.services.gemini_service.time.sleep") as mock_sleep, \
             patch("app.services.gemini_service.random.uniform", return_value=0.5):
            result = classify_email("subject", "sender@company.com", "snippet")

        assert result.signal == "APPLIED"
        assert client.models.generate_content.call_count == 2
        # First retry delay: 2s + 0.5 jitter
        mock_sleep.assert_called_once_with(2.5)

    def test_four_429s_exhausted_returns_parse_error(self):
        """Four consecutive 429 responses (1 initial + 3 retries) exhaust all attempts."""
        client = _build_client_mock(
            side_effect=[_make_429(), _make_429(), _make_429(), _make_429()]
        )

        with patch("app.services.gemini_service.genai.Client", return_value=client), \
             patch("app.services.gemini_service.time.sleep") as mock_sleep, \
             patch("app.services.gemini_service.random.uniform", return_value=0.0):
            result = classify_email("subject", "sender@company.com", "snippet")

        assert result.signal == "PARSE_ERROR"
        assert result.confidence == 0.0
        assert client.models.generate_content.call_count == 4
        # All 3 retry delays used: 2s, 4s, 8s
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [2.0, 4.0, 8.0]

    def test_irrelevant_signal_returned_as_is(self):
        """IRRELEVANT signal is returned unchanged — no status change triggered."""
        client = _build_client_mock(
            return_value=_mock_response(
                '{"company": null, "role": null, "signal": "IRRELEVANT", "confidence": 0.95}'
            )
        )

        result = _run_classify(client)

        assert result.signal == "IRRELEVANT"
        assert result.confidence == 0.95

    def test_irrelevant_low_confidence_not_overridden(self):
        """IRRELEVANT is never overwritten to BELOW_THRESHOLD — threshold only applies to actionable signals."""
        client = _build_client_mock(
            return_value=_mock_response(
                '{"company": null, "role": null, "signal": "IRRELEVANT", "confidence": 0.5}'
            )
        )

        result = _run_classify(client)

        assert result.signal == "IRRELEVANT"

    def test_markdown_fenced_json_is_parsed_correctly(self):
        """Gemini sometimes wraps JSON in markdown fences — these are stripped before parsing."""
        fenced = '```json\n{"company": "Acme", "role": "SWE", "signal": "REJECTED", "confidence": 0.88}\n```'
        client = _build_client_mock(return_value=_mock_response(fenced))

        result = _run_classify(client)

        assert result.signal == "REJECTED"
        assert result.confidence == 0.88

    def test_no_pii_in_log_output_during_classification(self, caplog):
        """Email subject, sender, and body content must never appear in log output."""
        client = _build_client_mock(
            return_value=_mock_response(
                '{"company": "Acme", "role": "SWE", "signal": "APPLIED", "confidence": 0.9}'
            )
        )

        subject = "Your application has been received — Software Engineer"
        sender = "recruiting@acmecorp.com"
        body = "Thank you for applying to the Software Engineer position at Acme Corp."

        with caplog.at_level(logging.DEBUG, logger="gemini_classifier"), \
             patch("app.services.gemini_service.genai.Client", return_value=client), \
             patch("app.services.gemini_service.time.sleep"), \
             patch("app.services.gemini_service.random.uniform", return_value=0.0):
            classify_email(subject, sender, body)

        log_output = caplog.text
        assert subject not in log_output
        assert sender not in log_output
        assert "Thank you for applying" not in log_output
        assert "recruiting@acmecorp.com" not in log_output

    def test_retry_uses_exponential_backoff_delays(self):
        """Retry delays follow 2s → 4s schedule for first two failures (jitter mocked to 0)."""
        success = _mock_response(
            '{"company": "X", "role": "Y", "signal": "OFFER", "confidence": 0.82}'
        )
        client = _build_client_mock(
            side_effect=[_make_429(), _make_429(), success]
        )

        with patch("app.services.gemini_service.genai.Client", return_value=client), \
             patch("app.services.gemini_service.time.sleep") as mock_sleep, \
             patch("app.services.gemini_service.random.uniform", return_value=0.0):
            result = classify_email("s", "s", "s")

        assert result.signal == "OFFER"
        sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleep_calls == [2.0, 4.0]
