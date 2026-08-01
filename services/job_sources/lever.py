
import os

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_json
)
from services.job_sources.job_match_service import job_matches_profile


def environment_flag(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def source_debug_enabled():
    return environment_flag(
        "JOB_SOURCE_DEBUG",
        default=False,
    )


class LeverJobSource(BaseJobSource):
    source_name = "Lever"
    source_type = "lever"
    requires_company_config = True

    base_url = "https://api.lever.co/v0/postings"

    def fetch_company_jobs(self, company_slug):
        if not company_slug or not company_slug.strip():
            raise ValueError(
                "A Lever company slug is required."
            )

        company_slug = company_slug.strip()
        url = f"{self.base_url}/{company_slug}"

        payload = fetch_json(
            url,
            params={"mode": "json"}
        )

        if not isinstance(payload, list):
            raise RuntimeError(
                f"Lever returned an unexpected response for "
                f"company '{company_slug}'."
            )

        return payload

    def normalize_job(self, job, company_name):
        categories = job.get("categories") or {}

        location = categories.get("location")
        employment_type = categories.get("commitment")
        department = categories.get("department")
        team = categories.get("team")

        description_parts = [
            job.get("description"),
            job.get("descriptionPlain"),
            job.get("additionalPlain")
        ]

        description = "\n\n".join(
            part.strip()
            for part in description_parts
            if part and part.strip()
        )

        posting_url = job.get("hostedUrl")
        apply_url = job.get("applyUrl") or posting_url

        return {
            "source": self.source_name,
            "external_id": job.get("id"),
            "company_name": company_name,
            "position_title": (
                job.get("text")
                or "Untitled Position"
            ),
            "location": location,
            "employment_type": employment_type,
            "salary": None,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": clean_html_text(description),
            "departments": [
                value
                for value in [department, team]
                if value
            ],
            "offices": [],
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None
        }

    def search_company(
        self,
        company_slug,
        company_name
    ):
        if not company_name or not company_name.strip():
            raise ValueError(
                "A company name is required."
            )

        raw_jobs = self.fetch_company_jobs(
            company_slug
        )

        normalized_jobs = []

        for raw_job in raw_jobs:
            job = self.normalize_job(
                raw_job,
                company_name.strip()
            )

            if not job["posting_url"]:
                continue

            normalized_jobs.append(job)

        return normalized_jobs

    def search(self, profile, source_config=None):
        if source_config is None:
            raise ValueError(
                "Lever requires a company source configuration."
            )

        jobs = self.search_company(
            company_slug=source_config.source_identifier,
            company_name=source_config.company_name
        )

        if source_debug_enabled():
            print(
                f"LEVER FILTER DEBUG | "
                f"Profile: {profile.name} | "
                f"Jobs evaluated: {len(jobs)}"
            )

        return [
            job
            for job in jobs
            if job_matches_profile(job, profile)
        ]
