"""Workday tenant extraction utilities.

Pure functions — no DB access, no side effects. Stdlib only.
"""

import re
from urllib.parse import urlparse

# Matches: {tenant}.wd1.myworkdayjobs.com, {tenant}.myworkday.com, etc.
_WORKDAY_HOST_RE = re.compile(
    r"^([^.]+)\.(wd\d+\.)?myworkday(jobs|site)?\.com$", re.IGNORECASE
)

_EMAIL_BRACKET_RE = re.compile(r"<([^>]+)>")


def extract_workday_tenant(source_url: str | None) -> str | None:
    """Extract the Workday tenant subdomain from a job posting URL.

    Examples:
        https://meredith.wd5.myworkdayjobs.com/...  -> "meredith"
        https://acme.myworkday.com/...               -> "acme"
        https://acme.myworkdaysite.com/...           -> "acme"
        https://www.google.com/...                   -> None
    """
    if not source_url:
        return None
    try:
        hostname = urlparse(source_url).hostname
    except Exception:
        return None
    if not hostname:
        return None
    match = _WORKDAY_HOST_RE.match(hostname)
    return match.group(1).lower() if match else None


def extract_tenant_from_sender(sender_email: str | None) -> str | None:
    """Extract the Workday tenant from a sender email address.

    Only matches ``{tenant}@myworkday.com`` (exact domain).
    Handles display-name format: ``"Workday <meredith@myworkday.com>"``.

    No static blocklist — callers validate the result against real DB data
    (active_tenants set or Application.workday_tenant query), which prevents
    false positives without blocking legitimate tenants like "myview" (SDM).
    """
    if not sender_email:
        return None
    # Extract email from display-name format if present
    bracket_match = _EMAIL_BRACKET_RE.search(sender_email)
    email = bracket_match.group(1) if bracket_match else sender_email.strip()
    parts = email.rsplit("@", 1)
    if len(parts) != 2:
        return None
    local, domain = parts
    if domain.lower() != "myworkday.com":
        return None
    return local.lower()
