
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
    keep_invalid=False,
    company_name=None,
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
        normalized_company_name = str(
            company_name or ""
        ).strip()

        if (
            normalized_company_name
            and normalized_company_name.lower()
            not in {
                "unknown",
                "unknown company",
            }
            and (
                not candidate.company_name
                or candidate.company_name
                == candidate.source_identifier
            )
        ):
            candidate.company_name = (
                normalized_company_name
            )

        if candidate.validation_status == "dismissed":
            return candidate, "already_blocked"

        if candidate.validation_status == "approved":
            return candidate, "already_approved"

        return candidate, "already_candidate"

    candidate = JobSourceCandidate(
        company_name=(
            str(company_name or "").strip()
            or source_identifier
        ),
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
            candidate.validation_status = "dismissed"
            return candidate, "invalid_rejected"

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
        "already_blocked": 0,
        "already_approved": 0,
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


def ingest_himalayas_job_sources(job):
    if not isinstance(job, dict):
        return {}

    if str(
        job.get("source") or ""
    ).strip().lower() != "himalayas":
        return {}

    urls = []

    for record in (
        job.get("source_candidates")
        or []
    ):
        if isinstance(record, dict):
            url = record.get("url")
        else:
            url = record

        normalized_url = str(
            url or ""
        ).strip()

        if normalized_url:
            urls.append(normalized_url)

    apply_url = str(
        job.get("apply_url") or ""
    ).strip()

    if apply_url:
        urls.append(apply_url)

    results = {}

    for url in dict.fromkeys(urls):
        try:
            _, status = ingest_source_url(
                url=url,
                discovery_method=(
                    "himalayas_feed_scan"
                ),
                auto_validate=False,
                company_name=job.get(
                    "company_name"
                ),
            )
        except ValueError:
            continue

        results[status] = (
            results.get(status, 0)
            + 1
        )

    return results


def validate_pending_himalayas_candidates(
    limit=5,
):
    normalized_limit = max(
        0,
        min(int(limit), 25),
    )

    if not normalized_limit:
        return {
            "checked": 0,
            "valid": 0,
            "invalid": 0,
        }

    candidates = (
        JobSourceCandidate.query
        .filter(
            JobSourceCandidate
            .validation_status
            == "pending",
            JobSourceCandidate
            .discovery_method
            .in_([
                "himalayas_feed_scan",
                "himalayas_browser_resolver",
            ]),
        )
        .order_by(
            JobSourceCandidate
            .discovered_at.asc()
        )
        .limit(normalized_limit)
        .all()
    )
    stats = {
        "checked": 0,
        "valid": 0,
        "invalid": 0,
    }

    for candidate in candidates:
        valid, _ = validate_source_candidate(
            candidate
        )
        stats["checked"] += 1
        stats[
            "valid"
            if valid
            else "invalid"
        ] += 1

    return stats
