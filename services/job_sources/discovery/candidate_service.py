
from models import JobSourceCandidate, JobSourceCompany, db
from services.job_sources.discovery.source_discovery import (
    detect_source_type
)
from services.job_sources.discovery.validation_service import (
    validate_source_candidate
)


def ingest_source_url(
    url,
    discovery_method="automatic_discovery",
    auto_validate=True,
    keep_invalid=False
):
    cleaned_url = (url or "").strip()

    if not cleaned_url:
        return None, "failed"

    source_type, source_identifier = detect_source_type(
        cleaned_url
    )

    existing_source = JobSourceCompany.query.filter_by(
        source_type=source_type,
        source_identifier=source_identifier
    ).first()

    if existing_source:
        return existing_source, "already_active"

    candidate = JobSourceCandidate.query.filter_by(
        source_type=source_type,
        source_identifier=source_identifier
    ).first()

    if candidate:
        return candidate, "already_candidate"

    candidate = JobSourceCandidate(
        company_name=source_identifier,
        source_type=source_type,
        source_identifier=source_identifier,
        discovered_url=cleaned_url,
        discovery_method=discovery_method,
        validation_status="pending"
    )

    db.session.add(candidate)
    db.session.flush()

    if auto_validate:
        valid, _ = validate_source_candidate(candidate)

        if not valid and not keep_invalid:
            db.session.delete(candidate)
            return None, "invalid_rejected"

    return candidate, "created"


def ingest_source_urls(
    urls,
    discovery_method="automatic_discovery",
    auto_validate=True,
    keep_invalid=False
):
    results = {
        "created": 0,
        "already_active": 0,
        "already_candidate": 0,
        "invalid_rejected": 0,
        "failed": 0
    }

    for url in urls:
        try:
            _, status = ingest_source_url(
                url=url,
                discovery_method=discovery_method,
                auto_validate=auto_validate,
                keep_invalid=keep_invalid
            )

            if status in results:
                results[status] += 1
            else:
                results["failed"] += 1

        except Exception as error:
            results["failed"] += 1

            print(
                f"AUTOMATIC SOURCE INGESTION FAILED | "
                f"URL: {url} | Error: {error}"
            )

    db.session.commit()

    return results
