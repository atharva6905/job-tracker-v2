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


def is_job_related(sender: str, subject: str) -> bool:
    """Return True if the email is likely job-application related."""
    sender_lower = sender.lower()
    for domain in KNOWN_ATS_DOMAINS:
        if domain in sender_lower:
            return True

    subject_lower = subject.lower()
    for keyword in JOB_SUBJECT_KEYWORDS:
        if keyword in subject_lower:
            return True

    return False
