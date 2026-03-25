"""
JD structuring service — extracts structured fields from raw job description text
using Gemini 2.5 Flash.

Idempotent: skips if structured_jd is already populated.
Same retry/backoff strategy as the email classifier.
"""

import json
import os
import random
import re
import time

from google import genai
from google.genai import errors as genai_errors
from sqlalchemy.orm import Session

from app.models.job_description import JobDescription
from app.utils.logging import get_logger

_logger = get_logger("jd_structuring")

STRUCTURING_PROMPT = """
You are extracting structured information from a job description.

Job description text:
{raw_text}

Respond ONLY with a JSON object, no markdown, no explanation:
{{
  "summary": "<1-3 sentence summary of the role>",
  "responsibilities": ["<responsibility 1>", "<responsibility 2>", ...],
  "required_qualifications": ["<qualification 1>", "<qualification 2>", ...],
  "preferred_qualifications": ["<qualification 1>", "<qualification 2>", ...],
  "tech_stack": ["<technology 1>", "<technology 2>", ...],
  "compensation": "<compensation info or null>",
  "application_deadline": "<ISO date string or null>",
  "location": "<location or null>",
  "work_model": "<Remote|Hybrid|On-site or null>",
  "company_overview": "<company description or null>"
}}

Rules:
- tech_stack: list programming languages, frameworks, tools, databases mentioned. Empty list if non-tech role.
- compensation: include salary range, hourly rate, or benefits summary if mentioned. null if not mentioned.
- application_deadline: ISO date (YYYY-MM-DD) if mentioned. null if not mentioned.
- work_model: exactly one of "Remote", "Hybrid", "On-site", or null if not mentioned.
- If a field has no relevant info, use empty list for arrays, null for optional strings.
"""

_VALID_KEYS = {
    "summary", "responsibilities", "required_qualifications",
    "preferred_qualifications", "tech_stack", "compensation",
    "application_deadline", "location", "work_model", "company_overview",
}


def _parse_response(text: str) -> dict | None:
    """Parse Gemini response into structured dict. Returns None on failure."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed.get("summary"), str):
        return None

    # Normalize: ensure all expected keys present with correct types
    result = {
        "summary": str(parsed.get("summary", "")),
        "responsibilities": _ensure_str_list(parsed.get("responsibilities")),
        "required_qualifications": _ensure_str_list(parsed.get("required_qualifications")),
        "preferred_qualifications": _ensure_str_list(parsed.get("preferred_qualifications")),
        "tech_stack": _ensure_str_list(parsed.get("tech_stack")),
        "compensation": parsed.get("compensation") or None,
        "application_deadline": parsed.get("application_deadline") or None,
        "location": parsed.get("location") or None,
        "work_model": _normalize_work_model(parsed.get("work_model")),
        "company_overview": parsed.get("company_overview") or None,
    }
    return result


def _ensure_str_list(val: object) -> list[str]:
    if not isinstance(val, list):
        return []
    return [str(item) for item in val if item]


def _normalize_work_model(val: object) -> str | None:
    if not isinstance(val, str):
        return None
    normalized = val.strip().lower()
    mapping = {"remote": "Remote", "hybrid": "Hybrid", "on-site": "On-site", "onsite": "On-site"}
    return mapping.get(normalized)


def structure_job_description(db: Session, job_description_id: str) -> None:
    """
    Load a JobDescription by ID, call Gemini to extract structured fields,
    and write to structured_jd. Idempotent — skips if already populated.
    """
    jd = db.get(JobDescription, job_description_id)
    if not jd:
        _logger.warning(
            "JobDescription not found",
            extra={"job_description_id": str(job_description_id), "action_taken": "not_found"},
        )
        return

    if jd.structured_jd is not None:
        _logger.info(
            "Structured JD already populated, skipping",
            extra={"job_description_id": str(job_description_id), "action_taken": "skip_idempotent"},
        )
        return

    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    prompt = STRUCTURING_PROMPT.format(raw_text=jd.raw_text[:50000])

    _retry_delays = [2, 4, 8]
    _max_attempts = len(_retry_delays) + 1

    for attempt in range(_max_attempts):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            text = response.text.strip()
            structured = _parse_response(text)

            if structured is None:
                _logger.warning(
                    "Failed to parse structured JD response",
                    extra={
                        "job_description_id": str(job_description_id),
                        "action_taken": "parse_error",
                    },
                )
                return

            jd.structured_jd = structured
            db.commit()
            _logger.info(
                "Structured JD saved",
                extra={
                    "job_description_id": str(job_description_id),
                    "action_taken": "structured",
                },
            )
            return

        except genai_errors.APIError as exc:
            if exc.code == 429 and attempt < len(_retry_delays):
                match = re.search(r"Please retry in (\d+(?:\.\d+)?)s", str(exc))
                delay = float(match.group(1)) if match else _retry_delays[attempt]
                delay += random.uniform(0, 1)
                time.sleep(delay)
            else:
                _logger.warning(
                    "Gemini API error during JD structuring",
                    exc_info=True,
                    extra={
                        "job_description_id": str(job_description_id),
                        "action_taken": "api_error",
                        "error_type": type(exc).__name__,
                    },
                )
                return

        except Exception as exc:
            _logger.warning(
                "JD structuring failed unexpectedly",
                extra={
                    "job_description_id": str(job_description_id),
                    "action_taken": "unexpected_error",
                    "error_type": type(exc).__name__,
                },
            )
            return

    _logger.warning(
        "Gemini rate limit exhausted during JD structuring",
        extra={
            "job_description_id": str(job_description_id),
            "action_taken": "rate_limit_exhausted",
        },
    )
