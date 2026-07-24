
from datetime import datetime, timezone

from services.job_sources.registry import create_source


def validate_source_candidate(candidate):
    try:
        source = create_source(candidate.source_type)

        if source is None:
            raise ValueError(
                f"No adapter exists for {candidate.source_type}."
            )

        temporary_config = SourceValidationConfig(
            company_name=(
                candidate.company_name
                or candidate.source_identifier
            ),
            source_identifier=candidate.source_identifier
        )

        if candidate.source_type == "greenhouse":
            jobs = source.fetch_company_jobs(
                temporary_config.source_identifier
            )

        elif candidate.source_type == "lever":
            jobs = source.fetch_company_jobs(
                temporary_config.source_identifier
            )

        elif candidate.source_type == "ashby":
            jobs = source.fetch_company_jobs(
                temporary_config.source_identifier
            )

        else:
            raise ValueError(
                f"Validation is not implemented for "
                f"{candidate.source_type}."
            )

        candidate.validation_status = "valid"
        candidate.validation_error = None
        candidate.last_validated_at = datetime.now(timezone.utc)

        return True, len(jobs)

    except Exception as error:
        candidate.validation_status = "invalid"
        candidate.validation_error = str(error)
        candidate.last_validated_at = datetime.now(timezone.utc)

        return False, 0


class SourceValidationConfig:
    def __init__(self, company_name, source_identifier):
        self.company_name = company_name
        self.source_identifier = source_identifier
        