
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


class GreenhouseJobSource(BaseJobSource):
    source_name = "Greenhouse"
    source_type = "greenhouse"
    requires_company_config = True
    base_url = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_company_jobs(self, board_token):
        if not board_token or not board_token.strip():
            raise ValueError(
                "A Greenhouse board token is required."
            )

        board_token = board_token.strip()
        url = f"{self.base_url}/{board_token}/jobs"

        payload = fetch_json(
            url,
            params={"content": "true"}
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Greenhouse returned an unexpected response for "
                f"board '{board_token}'."
            )

        jobs = payload.get("jobs", [])

        if not isinstance(jobs, list):
            raise RuntimeError(
                f"Greenhouse returned invalid jobs data for "
                f"board '{board_token}'."
            )

        return jobs

    def normalize_job(self, job, company_name):
        location_data = job.get("location") or {}
        departments = job.get("departments") or []
        offices = job.get("offices") or []

        department_names = [
            department.get("name")
            for department in departments
            if department.get("name")
        ]

        office_names = [
            office.get("name")
            for office in offices
            if office.get("name")
        ]

        posting_url = job.get("absolute_url")

        return {
            "source": self.source_name,
            "external_id": (
                str(job.get("id"))
                if job.get("id") is not None
                else None
            ),
            "company_name": company_name,
            "position_title": (
                job.get("title")
                or "Untitled Position"
            ),
            "location": location_data.get("name"),
            "employment_type": None,
            "salary": None,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(job.get("content")),
            "departments": department_names,
            "offices": office_names,
            "updated_at": job.get("updated_at")
        }

    def search_company(self, board_token, company_name):
        if not company_name or not company_name.strip():
            raise ValueError("A company name is required.")

        jobs = self.fetch_company_jobs(board_token)
        normalized_jobs = []

        for job in jobs:
            normalized_job = self.normalize_job(
                job,
                company_name.strip()
            )

            if normalized_job["posting_url"]:
                normalized_jobs.append(normalized_job)

        return normalized_jobs

    def search(self, profile, source_config=None):
        if source_config is None:
            raise ValueError(
                "Greenhouse requires a company source configuration."
            )

        jobs = self.search_company(
            board_token=source_config.source_identifier,
            company_name=source_config.company_name
        )

        if source_debug_enabled():
            print(
                f"GREENHOUSE FILTER DEBUG | "
                f"Profile: {profile.name} | "
                f"Jobs evaluated: {len(jobs)}"
            )

        return [
            job
            for job in jobs
            if job_matches_profile(job, profile)
        ]
