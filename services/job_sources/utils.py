
import hashlib


def build_job_fingerprint(
    company,
    position,
    location,
    posting_url
):
    normalized = "|".join([
        (company or "").strip().lower(),
        (position or "").strip().lower(),
        (location or "").strip().lower(),
        (posting_url or "").strip().lower()
    ])

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
    