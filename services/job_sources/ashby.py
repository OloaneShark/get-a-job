
import re

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json


class AshbyJobSource(BaseJobSource):
    source_name = "Ashby"
    source_type = "ashby"
    requires_company_config = True

    base_url = "https://api.ashbyhq.com/posting-api/job-board"

    def fetch_company_jobs(self, job_board_name):
        if not job_board_name or not job_board_name.strip():
            raise ValueError("An Ashby job-board name is required.")

        job_board_name = job_board_name.strip()
        url = f"{self.base_url}/{job_board_name}"

        payload = fetch_json(
            url,
            params={"includeCompensation": "true"}
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                f"Ashby returned an unexpected response for "
                f"board '{job_board_name}'."
            )

        jobs = payload.get("jobs", [])

        if not isinstance(jobs, list):
            raise RuntimeError(
                f"Ashby returned invalid jobs data for "
                f"board '{job_board_name}'."
            )

        return jobs

    def normalize_job(self, job, company_name):
        compensation = job.get("compensation") or {}

        salary = (
            compensation.get("scrapeableCompensationSalarySummary")
            or compensation.get("compensationTierSummary")
        )

        department = job.get("department")
        team = job.get("team")
        posting_url = job.get("jobUrl")
        apply_url = job.get("applyUrl") or posting_url

        description = (
            job.get("descriptionPlain")
            or clean_html_text(job.get("descriptionHtml"))
        )

        return {
            "source": self.source_name,
            "external_id": posting_url,
            "company_name": company_name,
            "position_title": job.get("title") or "Untitled Position",
            "location": job.get("location"),
            "employment_type": job.get("employmentType"),
            "salary": salary,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": description,
            "departments": [
                value
                for value in [department, team]
                if value
            ],
            "offices": [],
            "is_remote": bool(job.get("isRemote")),
            "workplace_type": job.get("workplaceType"),
            "published_at": job.get("publishedAt"),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None
        }

    def search_company(self, job_board_name, company_name):
        if not company_name or not company_name.strip():
            raise ValueError("A company name is required.")

        raw_jobs = self.fetch_company_jobs(job_board_name)
        normalized_jobs = []

        for raw_job in raw_jobs:
            if raw_job.get("isListed") is False:
                continue

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
                "Ashby requires a company source configuration."
            )

        jobs = self.search_company(
            job_board_name=source_config.source_identifier,
            company_name=source_config.company_name
        )

        keywords = self.parse_values(profile.keywords)
        locations = self.parse_values(profile.locations)

        print(
            f"ASHBY FILTER DEBUG | "
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
            pattern = (
                r"(?<!\w)"
                + re.escape(keyword)
                + r"(?!\w)"
            )

            if re.search(pattern, searchable_text):
                return True

        return False

    @staticmethod
    def matches_locations(job, locations, remote_only=False):
        job_location = (job.get("location") or "").strip().lower()
        workplace_type = (
            job.get("workplace_type")
            or ""
        ).strip().lower()

        is_remote = (
            job.get("is_remote")
            or workplace_type == "remote"
            or "remote" in job_location
        )

        if remote_only and not is_remote:
            return False

        if not locations:
            return True

        return any(
            location in job_location
            for location in locations
        )
        
