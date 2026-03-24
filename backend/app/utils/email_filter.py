from app.utils.logging import get_logger

_logger = get_logger("email_pre_filter")

KNOWN_ATS_DOMAINS = [
    "greenhouse.io",
    "lever.co",
    "myworkday.com",
    "ashbyhq.com",
    "icims.com",
    "smartrecruiters.com",
    "taleo.net",
    "successfactors.com",
]

JOB_SUBJECT_KEYWORDS = [
    "application",
    "interview",
    "offer",
    "next steps",
    "unfortunately",
    "thank you for applying",
    "thanks for applying",
    "thank you for your interest",
    "thanks for your interest",
    "thanks for your application",
    "we received your",
    "application received",
    "application submitted",
    "your application",
    "position",
    "opportunity",
    "career",
    "hiring",
    "candidate",
    "moving forward",
    "not moving forward",
    "next round",
    "phone screen",
    "technical interview",
]


def _extract_domain(sender: str) -> str:
    """Extract the email domain from a sender string.

    Handles both plain addresses (user@domain.com) and display-name
    format (Display Name <user@domain.com>).
    """
    # Strip display name wrapper if present
    if "<" in sender and ">" in sender:
        sender = sender.split("<")[1].split(">")[0]
    # Extract domain after @
    _, _, domain = sender.rpartition("@")
    return domain.lower()


def is_job_related(sender: str, subject: str) -> bool:
    """Return True if the email is likely job-application related."""
    domain = _extract_domain(sender)
    for ats_domain in KNOWN_ATS_DOMAINS:
        if ats_domain in domain:
            _logger.debug(
                "Pre-filter pass",
                extra={"action_taken": "pre_filter_pass", "match_type": "ats_domain"},
            )
            return True

    subject_lower = subject.lower()
    for keyword in JOB_SUBJECT_KEYWORDS:
        if keyword in subject_lower:
            _logger.debug(
                "Pre-filter pass",
                extra={"action_taken": "pre_filter_pass", "match_type": "subject_keyword"},
            )
            return True

    return False
