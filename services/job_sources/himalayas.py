
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class HimalayasJobSource(BaseJobSource):
    source_name = "Himalayas"
    source_type = "himalayas"
    requires_company_config = False

    feed_url = "https://himalayas.app/jobs/api"

    # Himalayas refreshes its public API data every 24 hours,
    # so there is no benefit to fetching it every 15 minutes.
    cache_duration = timedelta(hours=24)
    page_limit = 20
    max_pages_per_refresh = 10

    _cached_jobs = None
    _cache_fetched_at = None
    _cache_lock = threading.Lock()

    @classmethod
    def cache_is_fresh(cls):
        if cls._cached_jobs is None:
            return False

        if cls._cache_fetched_at is None:
            return False

        cache_age = (
            datetime.now(timezone.utc)
            - cls._cache_fetched_at
        )

        return cache_age < cls.cache_duration

    @staticmethod
    def format_salary(raw_job):
        minimum = raw_job.get("minSalary")
        maximum = raw_job.get("maxSalary")
        currency = raw_job.get("currency") or ""
        period = raw_job.get("salaryPeriod") or "annual"

        if minimum is None and maximum is None:
            return None

        currency_prefix = f"{currency} " if currency else ""

        if minimum is not None and maximum is not None:
            salary_text = (
                f"{currency_prefix}"
                f"{minimum:,.0f} - {maximum:,.0f}"
            )
        elif minimum is not None:
            salary_text = (
                f"From {currency_prefix}"
                f"{minimum:,.0f}"
            )
        else:
            salary_text = (
                f"Up to {currency_prefix}"
                f"{maximum:,.0f}"
            )

        return f"{salary_text} per {period}"

    @staticmethod
    def format_location(raw_job):
        restrictions = raw_job.get("locationRestrictions") or []
        location_names = []

        for restriction in restrictions:
            if not isinstance(restriction, dict):
                continue

            location_name = (
                restriction.get("name")
                or restriction.get("alpha2")
                or restriction.get("slug")
            )

            if location_name:
                location_names.append(str(location_name).strip())

        if not location_names:
            return "Worldwide"

        return " | ".join(location_names)

    @staticmethod
    def normalize_employment_type(value):
        normalized = str(value or "").strip()

        mapping = {
            "Full Time": "Full-time",
            "Part Time": "Part-time",
            "Contractor": "Contract",
            "Temporary": "Temporary",
            "Intern": "Internship",
            "Volunteer": "Volunteer",
            "Other": "Other",
        }

        return mapping.get(normalized, normalized or None)

    def fetch_jobs(self):
        jobs = []
        offset = 0
        total_count = None

        for page_number in range(1, self.max_pages_per_refresh + 1):
            payload = fetch_json(
                self.feed_url,
                params={
                    "offset": offset,
                    "limit": self.page_limit,
                },
            )

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Himalayas returned an unexpected response."
                )

            page_jobs = payload.get("jobs", [])

            if not isinstance(page_jobs, list):
                raise RuntimeError(
                    "Himalayas returned invalid jobs data."
                )

            if total_count is None:
                total_count = payload.get("totalCount")

            jobs.extend(
                raw_job
                for raw_job in page_jobs
                if isinstance(raw_job, dict)
            )

            print(
                "HIMALAYAS FETCH PROGRESS | "
                f"Page: {page_number} | "
                f"Jobs collected: {len(jobs)}"
            )

            if len(page_jobs) < self.page_limit:
                break

            offset += self.page_limit

            if isinstance(total_count, int) and offset >= total_count:
                break

        return jobs

    def normalize_job(self, raw_job):
        posting_url = raw_job.get("applicationLink")
        categories = raw_job.get("categories") or []
        parent_categories = raw_job.get("parentCategories") or []
        seniority = raw_job.get("seniority") or []

        departments = []

        for value in list(categories) + list(parent_categories) + list(seniority):
            if value and value not in departments:
                departments.append(value)

        description = raw_job.get("description") or raw_job.get("excerpt")

        return {
            "source": self.source_name,
            "external_id": (
                str(raw_job.get("guid"))
                if raw_job.get("guid") is not None
                else posting_url
            ),
            "company_name": (
                raw_job.get("companyName")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("title")
                or "Untitled Position"
            ),
            "location": self.format_location(raw_job),
            "employment_type": self.normalize_employment_type(
                raw_job.get("employmentType")
            ),
            "salary": self.format_salary(raw_job),
            "visa_sponsorship": "Unknown",
            # Himalayas requires visible attribution and a link
            # back to the original Himalayas job listing.
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(description),
            "departments": departments,
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": raw_job.get("pubDate"),
            "expires_at": raw_job.get("expiryDate"),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    def get_cached_jobs(self):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                print(
                    "HIMALAYAS CACHE | "
                    f"Using {len(source_class._cached_jobs)} "
                    "cached jobs."
                )

                return list(source_class._cached_jobs)

            raw_jobs = self.fetch_jobs()

            normalized_jobs = [
                self.normalize_job(raw_job)
                for raw_job in raw_jobs
            ]

            normalized_jobs = [
                job
                for job in normalized_jobs
                if job.get("posting_url")
            ]

            source_class._cached_jobs = normalized_jobs
            source_class._cache_fetched_at = datetime.now(timezone.utc)

            print(
                "HIMALAYAS FEED | "
                f"Fetched {len(normalized_jobs)} jobs."
            )

            return list(normalized_jobs)

    def search(self, profile, source_config=None):
        jobs = self.get_cached_jobs()

        matching_jobs = [
            job
            for job in jobs
            if job_matches_profile(job, profile)
        ]

        print(
            f"HIMALAYAS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
