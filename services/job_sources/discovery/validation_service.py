
from datetime import datetime, timezone

from services.job_sources.registry import create_source


MINIMUM_VALID_JOBS = 1


class SourceValidationConfig:
    def __init__(self, company_name, source_identifier):
        self.company_name = company_name
        self.source_identifier = source_identifier


def has_usable_job_data(job):
    if not isinstance(job, dict):
        return False

    title = (
        job.get("title")
        or job.get("position_title")
        or ""
    )

    posting_url = (
        job.get("absolute_url")
        or job.get("hostedUrl")
        or job.get("jobUrl")
        or job.get("posting_url")
        or job.get("applyUrl")
        or job.get("apply_url")
        or ""
    )

    return bool(
        str(title).strip()
        and str(posting_url).strip()
    )


def detect_company_name(jobs, fallback):
    for job in jobs:
        if not isinstance(job, dict):
            continue

        company_name = (
            job.get("company")
            or job.get("company_name")
            or job.get("organization")
        )

        if isinstance(company_name, dict):
            company_name = (
                company_name.get("name")
                or company_name.get("text")
            )

        if company_name and str(company_name).strip():
            return str(company_name).strip()

    return fallback


def validate_source_candidate(candidate):
    candidate.last_validated_at = datetime.now(timezone.utc)

    try:
        source = create_source(candidate.source_type)

        if source is None:
            raise ValueError(
                f"No adapter exists for "
                f"{candidate.source_type}."
            )

        temporary_config = SourceValidationConfig(
            company_name=(
                candidate.company_name
                or candidate.source_identifier
            ),
            source_identifier=candidate.source_identifier
        )

        jobs = source.fetch_company_jobs(
            temporary_config.source_identifier
        )

        if not isinstance(jobs, list):
            raise ValueError(
                "The source returned an invalid jobs response."
            )

        usable_jobs = [
            job
            for job in jobs
            if has_usable_job_data(job)
        ]

        if len(usable_jobs) < MINIMUM_VALID_JOBS:
            raise ValueError(
                "The board returned no usable current job postings."
            )

        candidate.company_name = detect_company_name(
            usable_jobs,
            candidate.company_name
            or candidate.source_identifier
        )

        candidate.validation_status = "valid"
        candidate.validation_error = None

        print(
            f"SOURCE VALIDATION SUCCESS | "
            f"Source: {candidate.source_type} | "
            f"Identifier: {candidate.source_identifier} | "
            f"Usable jobs: {len(usable_jobs)}"
        )

        return True, len(usable_jobs)

    except Exception as error:
        candidate.validation_status = "invalid"
        candidate.validation_error = str(error)

        print(
            f"SOURCE VALIDATION FAILED | "
            f"Source: {candidate.source_type} | "
            f"Identifier: {candidate.source_identifier} | "
            f"Error: {error}"
        )

        return False, 0
    