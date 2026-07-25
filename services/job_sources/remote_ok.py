
import re

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_json,
)


class RemoteOKJobSource(BaseJobSource):
    source_name = "Remote OK"
    source_type = "remote_ok"
    requires_company_config = False

    feed_url = "https://remoteok.com/api"

    def fetch_jobs(self):
        payload = fetch_json(self.feed_url)

        if not isinstance(payload, list):
            raise RuntimeError(
                "Remote OK returned an unexpected response."
            )

        jobs = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            # Remote OK commonly places feed metadata first.
            if not item.get("id"):
                continue

            if not item.get("position"):
                continue

            jobs.append(item)

        return jobs

    def normalize_job(self, raw_job):
        posting_url = (
            raw_job.get("url")
            or raw_job.get("apply_url")
        )

        description = clean_html_text(
            raw_job.get("description")
        )

        tags = raw_job.get("tags") or []

        if not isinstance(tags, list):
            tags = []

        location = raw_job.get("location") or "Remote"

        salary_min = raw_job.get("salary_min")
        salary_max = raw_job.get("salary_max")

        salary = None

        if salary_min and salary_max:
            salary = (
                f"${salary_min:,} - "
                f"${salary_max:,}"
            )
        elif salary_min:
            salary = f"From ${salary_min:,}"
        elif salary_max:
            salary = f"Up to ${salary_max:,}"

        return {
            "source": self.source_name,
            "external_id": str(raw_job.get("id")),
            "company_name": (
                raw_job.get("company")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("position")
                or "Untitled Position"
            ),
            "location": location,
            "employment_type": "Full-time",
            "salary": salary,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": tags,
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": (
                raw_job.get("date")
                or raw_job.get("epoch")
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    def search(self, profile, source_config=None):
        raw_jobs = self.fetch_jobs()

        keywords = self.parse_values(
            profile.keywords
        )

        locations = self.parse_values(
            profile.locations
        )

        print(
            f"REMOTE OK FILTER DEBUG | "
            f"Profile: {profile.name} | "
            f"Remote only: {profile.remote_only} | "
            f"Keywords: {keywords} | "
            f"Locations: {locations}"
        )

        matching_jobs = []

        for raw_job in raw_jobs:
            job = self.normalize_job(raw_job)

            if not job["posting_url"]:
                continue

            if not self.matches_keywords(
                job,
                keywords
            ):
                continue

            if not self.matches_experience_level(
                job,
                keywords
            ):
                continue

            if not self.matches_location_preferences(
                job,
                locations
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

        title = (
            job.get("position_title")
            or ""
        ).strip().lower()

        description = (
            job.get("job_description")
            or ""
        ).lower()

        tags = " ".join(
            job.get("departments")
            or []
        ).lower()

        excluded_title_terms = {
            "account executive",
            "account manager",
            "business development",
            "customer success",
            "marketing",
            "sales",
            "sales development",
            "recruiter",
            "recruiting",
            "human resources",
            "hr manager",
            "product manager",
            "project manager"
        }

        if any(
            excluded_term in title
            for excluded_term in excluded_title_terms
        ):
            return False

        for keyword in keywords:
            keyword = keyword.strip().lower()

            if not keyword:
                continue

            pattern = (
                r"(?<!\w)"
                + re.escape(keyword)
                + r"(?!\w)"
            )

            # A direct title match is strong enough by itself.
            if re.search(pattern, title):
                return True

        # Only use the description and tags as supporting evidence.
        supporting_matches = 0

        for keyword in keywords:
            keyword = keyword.strip().lower()

            if not keyword:
                continue

            pattern = (
                r"(?<!\w)"
                + re.escape(keyword)
                + r"(?!\w)"
            )

            if re.search(pattern, description):
                supporting_matches += 1

            if re.search(pattern, tags):
                supporting_matches += 1

        technical_title_terms = {
            "developer",
            "engineer",
            "programmer",
            "software",
            "frontend",
            "front end",
            "backend",
            "back end",
            "fullstack",
            "full stack",
            "devops",
            "security",
            "cloud",
            "data",
            "qa",
            "quality assurance",
            "site reliability",
            "sre"
        }

        has_technical_title = any(
            term in title
            for term in technical_title_terms
        )

        return (
            has_technical_title
            and supporting_matches >= 1
        )

    @staticmethod
    def matches_location_preferences(
        job,
        locations,
    ):
        if not locations:
            return True

        job_location = (
            job.get("location")
            or ""
        ).strip().lower()

        if not job_location:
            return True

        if job_location == "remote":
            return True

        searchable_location = (
            f"remote {job_location}"
        )

        return any(
            location in searchable_location
            for location in locations
        )
        
    @staticmethod
    def matches_experience_level(job, keywords):
        title = (
            job.get("position_title")
            or ""
        ).strip().lower()

        description = (
            job.get("job_description")
            or ""
        ).lower()

        requested_internship = any(
            keyword in {
                "intern",
                "internship"
            }
            for keyword in keywords
        )

        if not requested_internship:
            return True

        senior_terms = {
            "senior",
            "sr.",
            "sr ",
            "lead",
            "principal",
            "staff",
            "manager",
            "director",
            "head of",
            "vice president",
            "vp "
        }

        if any(
            term in title
            for term in senior_terms
        ):
            return False

        internship_terms = {
            "intern",
            "internship",
            "student",
            "graduate",
            "entry level",
            "entry-level",
            "junior"
        }

        combined_text = f"{title} {description}"

        return any(
            term in combined_text
            for term in internship_terms
        )
