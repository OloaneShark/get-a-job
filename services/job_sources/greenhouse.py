
import re
from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_json
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

        board_token = source_config.source_identifier
        company_name = source_config.company_name

        jobs = self.search_company(
            board_token=board_token,
            company_name=company_name
        )

        keywords = self.parse_values(profile.keywords)
        locations = self.parse_values(profile.locations)

        print(
            f"GREENHOUSE FILTER DEBUG | "
            f"Profile: {profile.name} | "
            f"Remote only: {profile.remote_only} | "
            f"Keywords: {keywords} | "
            f"Locations: {locations}"
        )

        matching_jobs = []

        for job in jobs:
            if not self.matches_keywords(job, keywords):
                continue

            if not self.matches_locations(
                job,
                locations,
                profile.remote_only
            ):
                continue

            matching_jobs.append(job)

        return matching_jobs

    @staticmethod
    def parse_values(value):
        if not value:
            return []

        return [
            item.strip().lower()
            for item in re.split(r"[\n,]+", value)
            if item.strip()
        ]

    @staticmethod
    def matches_keywords(job, keywords):
        if not keywords:
            return True

        title = job.get("position_title") or ""
        description = job.get("job_description") or ""
        departments = " ".join(job.get("departments") or [])

        searchable_text = " ".join([
            title,
            description,
            departments
        ]).lower()

        for keyword in keywords:
            normalized_keyword = keyword.strip().lower()

            if not normalized_keyword:
                continue

            pattern = (
                r"(?<!\w)"
                + re.escape(normalized_keyword)
                + r"(?!\w)"
            )

            if re.search(pattern, searchable_text):
                return True

        return False

    @staticmethod
    def matches_locations(job, locations, remote_only=False):
        job_location = (
            job.get("location")
            or ""
        ).strip().lower()

        if remote_only and "remote" not in job_location:
            return False

        if not locations:
            return True

        return any(
            location.strip().lower() in job_location
            for location in locations
            if location.strip()
        )
        