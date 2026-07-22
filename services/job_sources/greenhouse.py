
import html
import re

import requests

from services.job_sources.base import BaseJobSource


class GreenhouseJobSource(BaseJobSource):
    source_name = "Greenhouse"
    base_url = "https://boards-api.greenhouse.io/v1/boards"

    def fetch_company_jobs(self, board_token):
        if not board_token or not board_token.strip():
            raise ValueError("A Greenhouse board token is required.")

        url = f"{self.base_url}/{board_token.strip()}/jobs"

        try:
            response = requests.get(
                url,
                params={"content": "true"},
                timeout=20
            )

            response.raise_for_status()

        except requests.Timeout as e:
            raise RuntimeError(
                f"Greenhouse request timed out for board "
                f"'{board_token}'."
            ) from e

        except requests.RequestException as e:
            raise RuntimeError(
                f"Greenhouse request failed for board "
                f"'{board_token}': {e}"
            ) from e

        try:
            payload = response.json()

        except ValueError as e:
            raise RuntimeError(
                f"Greenhouse returned invalid JSON for board "
                f"'{board_token}'."
            ) from e

        return payload.get("jobs", [])

    def clean_description(self, content):
        if not content:
            return None

        decoded = html.unescape(content)

        decoded = re.sub(
            r"<\s*br\s*/?\s*>",
            "\n",
            decoded,
            flags=re.IGNORECASE
        )

        decoded = re.sub(
            r"</\s*(p|div|li|h[1-6])\s*>",
            "\n",
            decoded,
            flags=re.IGNORECASE
        )

        decoded = re.sub(
            r"<[^>]+>",
            "",
            decoded
        )

        decoded = re.sub(
            r"\n{3,}",
            "\n\n",
            decoded
        )

        return decoded.strip() or None

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
            "job_description": self.clean_description(
                job.get("content")
            ),
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

            if not normalized_job["posting_url"]:
                continue

            normalized_jobs.append(normalized_job)

        return normalized_jobs

    def search(self, profile, board_token, company_name):
        jobs = self.search_company(
            board_token=board_token,
            company_name=company_name
        )

        keywords = self.parse_values(
            profile.keywords
        )

        locations = self.parse_values(
            profile.locations
        )

        employment_types = self.parse_values(
            profile.employment_types
        )

        if any(
            employment_type.lower() in {"all", "any"}
            for employment_type in employment_types
        ):
            employment_types = []

        matching_jobs = []

        for job in jobs:
            if not self.matches_keywords(
                job,
                keywords
            ):
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
            item.strip()
            for item in re.split(r"[\n,]+", value)
            if item.strip()
        ]

    @staticmethod
    def matches_keywords(job, keywords):
        if not keywords:
            return True

        searchable_text = " ".join([
            job.get("position_title") or "",
            job.get("job_description") or "",
            " ".join(job.get("departments") or [])
        ]).lower()

        return any(
            keyword.lower() in searchable_text
            for keyword in keywords
        )

    @staticmethod
    def matches_locations(
        job,
        locations,
        remote_only=False
    ):
        job_location = (
            job.get("location")
            or ""
        ).lower()

        if remote_only:
            return "remote" in job_location

        if not locations:
            return True

        return any(
            location.lower() in job_location
            or job_location in location.lower()
            for location in locations
        )
        