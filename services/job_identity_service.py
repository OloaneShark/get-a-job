import hashlib
from urllib.parse import urlsplit, urlunsplit


def canonical_job_url(value):
    raw_value = str(value or "").strip()

    if not raw_value:
        return ""

    try:
        parsed = urlsplit(raw_value)
    except ValueError:
        return raw_value.split("#", 1)[0].rstrip("/")

    if not parsed.scheme or not parsed.netloc:
        return raw_value.split("#", 1)[0].rstrip("/")

    path = parsed.path.rstrip("/") or "/"

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            parsed.query,
            "",
        )
    )


def job_url_key(value):
    canonical_url = canonical_job_url(value)

    if not canonical_url:
        return ""

    return hashlib.sha256(
        canonical_url.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()
