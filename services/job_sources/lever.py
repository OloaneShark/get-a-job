
import html
import re

import requests

from services.job_sources.base import BaseJobSource


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

        url = f"{self.base_url}/{company_slug.strip()}"

        try:
            response = requests.get(
                url,
                params={"mode": "json"},
                timeout=20
            )

            response.raise_for_status()

        except requests.Timeout as error:
            raise RuntimeError(
                f"Lever request timed out for "
                f"company '{company_slug}'."
            ) from error

        except requests.RequestException as error:
            raise RuntimeError(
                f"Lever request failed for "
                f"company '{company_slug}': {error}"
            ) from error

        try:
            payload = response.json()

        except ValueError as error:
            raise RuntimeError(
                f"Lever returned invalid JSON for "
                f"company '{company_slug}'."
            ) from error

        if not isinstance(payload, list):
            raise RuntimeError(
                f"Lever returned an unexpected response for "
                f"company '{company_slug}'."
            )

        return payload


    @staticmethod
    def clean_description(value):
        if not value:
            return None

        decoded = html.unescape(value)

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
            "job_description": self.clean_description(
                description
            ),
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

        keywords = self.parse_values(
            profile.keywords
        )

        locations = self.parse_values(
            profile.locations
        )

        print(
            f"LEVER FILTER DEBUG | "
            f"Profile: {profile.name} | "
            f"Remote only: {profile.remote_only} | "
            f"Keywords: {keywords} | "
            f"Locations: {locations}"
        )

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
        departments = " ".join(
            job.get("departments") or []
        )

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
    def matches_locations(
        job,
        locations,
        remote_only=False
    ):
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
        
