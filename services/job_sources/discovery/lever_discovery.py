
from datetime import datetime, timezone
from urllib.parse import urlparse

from models import JobSourceCandidate, JobSourceCompany, db
from services.job_sources.http_client import fetch_json


LEVER_POSTINGS_BASE_URL = "https://api.lever.co/v0/postings"


def extract_lever_slug(url):
    if not url:
        return None

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    if hostname != "jobs.lever.co":
        return None

    path_parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if not path_parts:
        return None

    return path_parts[0].strip().lower()


def validate_lever_slug(slug):
    if not slug:
        return False, None, "Missing Lever company slug."

    url = f"{LEVER_POSTINGS_BASE_URL}/{slug}"

    try:
        payload = fetch_json(
            url,
            params={"mode": "json"}
        )

        if not isinstance(payload, list):
            return False, None, "Lever returned an unexpected response."

        company_name = None

        if payload:
            first_job = payload[0]
            company_name = (
                first_job.get("company")
                or first_job.get("categories", {}).get("team")
            )

        return True, company_name, None

    except Exception as error:
        return False, None, str(error)


def save_lever_candidate(
    slug,
    discovered_url=None,
    company_name=None,
    discovery_method="public_link"
):
    slug = (slug or "").strip().lower()

    if not slug:
        return None

    existing_source = JobSourceCompany.query.filter_by(
        source_type="lever",
        source_identifier=slug
    ).first()

    if existing_source:
        return None

    candidate = JobSourceCandidate.query.filter_by(
        source_type="lever",
        source_identifier=slug
    ).first()

    if candidate is None:
        candidate = JobSourceCandidate(
            source_type="lever",
            source_identifier=slug,
            discovered_url=discovered_url,
            company_name=company_name,
            discovery_method=discovery_method
        )

        db.session.add(candidate)

    valid, detected_company_name, error = validate_lever_slug(slug)

    candidate.last_validated_at = datetime.now(timezone.utc)

    if valid:
        candidate.validation_status = "valid"
        candidate.validation_error = None

        if not candidate.company_name:
            candidate.company_name = detected_company_name
    else:
        candidate.validation_status = "invalid"
        candidate.validation_error = error

    db.session.commit()

    return candidate
