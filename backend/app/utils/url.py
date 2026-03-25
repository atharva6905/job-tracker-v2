from urllib.parse import urlparse, urlunparse


def normalize_source_url(url: str) -> str:
    """Normalize a source URL for dedup: strip query params, hash, trailing slash.

    Must match normalizeSourceUrl() in extension/background.js and content.js.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
