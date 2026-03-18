"""
Gemini 2.5 Flash email classification service.

=============================================================================
LOG HYGIENE: Never log subject, sender, body_snippet, or any user-authored text.
Permitted log fields only: gemini_signal, gemini_confidence, action_taken,
error_type, timestamps.
=============================================================================
"""

import json
import os
import random
import time
from dataclasses import dataclass

from google import genai
from google.genai import errors as genai_errors

from app.utils.logging import get_logger

_logger = get_logger("gemini_classifier")

CLASSIFICATION_PROMPT = """
You are classifying a job application email.

Email subject: {subject}
Email sender: {sender}
Email body: {body_snippet}

Respond ONLY with a JSON object, no markdown, no explanation:
{{
  "company": "<company name or null>",
  "role": "<job title or null>",
  "signal": "APPLIED|INTERVIEW|OFFER|REJECTED|IRRELEVANT",
  "confidence": <0.0 to 1.0>
}}

signal definitions:
- APPLIED: confirms a job application was received by the employer
- INTERVIEW: invites the candidate to interview or schedule a screening call
- OFFER: extends a job offer to the candidate
- REJECTED: informs the candidate they will not be moving forward
- IRRELEVANT: this email is not related to a job application
"""

_VALID_SIGNALS = {"APPLIED", "INTERVIEW", "OFFER", "REJECTED", "IRRELEVANT"}
_ACTIONABLE_SIGNALS = {"APPLIED", "INTERVIEW", "OFFER", "REJECTED"}
_CONFIDENCE_THRESHOLD = 0.75


@dataclass
class GeminiClassificationResult:
    company: str | None
    role: str | None
    signal: str  # APPLIED|INTERVIEW|OFFER|REJECTED|IRRELEVANT|BELOW_THRESHOLD|PARSE_ERROR
    confidence: float


def _parse_error() -> GeminiClassificationResult:
    return GeminiClassificationResult(
        signal="PARSE_ERROR", confidence=0.0, company=None, role=None
    )


def classify_email(
    subject: str, sender: str, body_snippet: str
) -> GeminiClassificationResult:
    """
    Classify an email using Gemini 2.5 Flash.

    Returns a GeminiClassificationResult with:
    - signal: one of APPLIED, INTERVIEW, OFFER, REJECTED, IRRELEVANT,
              BELOW_THRESHOLD (confidence gate), or PARSE_ERROR (API failure)
    - confidence: raw confidence from Gemini (preserved even for BELOW_THRESHOLD)
    - company / role: extracted metadata (may be None)

    Retries on HTTP 429 with exponential backoff: 2s → 4s → 8s (each with up
    to 1s jitter). Returns PARSE_ERROR after exhausting all three attempts.
    """
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

    prompt = CLASSIFICATION_PROMPT.format(
        subject=subject,
        sender=sender,
        body_snippet=body_snippet,
    )

    _retry_delays = [2, 4, 8]

    for attempt in range(len(_retry_delays)):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text.strip()

            # Strip markdown fences if present — find first '{' to last '}'
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                raise ValueError("No JSON object found in response")
            text = text[start : end + 1]

            parsed = json.loads(text)

            signal = str(parsed.get("signal", ""))
            if signal not in _VALID_SIGNALS:
                raise ValueError(f"Unknown signal: {signal!r}")

            confidence = float(parsed.get("confidence", 0.0))
            company = parsed.get("company") or None
            role = parsed.get("role") or None

            # Confidence gate — only applies to actionable signals, not IRRELEVANT
            if signal in _ACTIONABLE_SIGNALS and confidence < _CONFIDENCE_THRESHOLD:
                signal = "BELOW_THRESHOLD"

            result = GeminiClassificationResult(
                company=company,
                role=role,
                signal=signal,
                confidence=confidence,
            )
            _logger.info(
                "Email classified",
                extra={
                    "gemini_signal": result.signal,
                    "gemini_confidence": result.confidence,
                    "action_taken": "classified",
                },
            )
            return result

        except genai_errors.ClientError as exc:
            if exc.code == 429:
                if attempt < len(_retry_delays) - 1:
                    delay = _retry_delays[attempt] + random.uniform(0, 1)
                    time.sleep(delay)
                # On the last attempt, fall through to PARSE_ERROR below
            else:
                _logger.warning(
                    "Gemini API client error",
                    extra={
                        "gemini_signal": "PARSE_ERROR",
                        "gemini_confidence": 0.0,
                        "action_taken": "api_error",
                        "error_type": type(exc).__name__,
                    },
                )
                return _parse_error()

        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            _logger.warning(
                "Gemini response parse failed",
                extra={
                    "gemini_signal": "PARSE_ERROR",
                    "gemini_confidence": 0.0,
                    "action_taken": "parse_error",
                    "error_type": type(exc).__name__,
                },
            )
            return _parse_error()

    _logger.warning(
        "Gemini rate limit exhausted after retries",
        extra={
            "gemini_signal": "PARSE_ERROR",
            "gemini_confidence": 0.0,
            "action_taken": "rate_limit_exhausted",
        },
    )
    return _parse_error()
