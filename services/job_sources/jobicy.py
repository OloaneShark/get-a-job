
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class JobicyJobSource(BaseJobSource):
    source_name = "Jobicy"
    source_type = "jobicy"
    requires_company_config = False

    feed_url = "https://jobicy.com/api/v2/remote-jobs"

    # Jobicy says automated checks must not run more than once per hour,
    # and that a few checks per day are normally enough.
    # Cache for six hours so the 15-minute scheduler does not over-poll.
    cache_duration = timedelta(hours=6)
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
    def normalize_employment_type(values):
        if not values:
            return None

        if not isinstance(values, list):
            values = [values]

        normalized_values = {
            str(value or "")
            .strip()
            .lower()
            .replace("_", "-")
            for value in values
            if str(value or "").strip()
        }

        mapping = {
            "full-time": "Full-time",
            "full time": "Full-time",
            "part-time": "Part-time",
            "part time": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "freelance": "Contract",
            "temporary": "Temporary",
            "internship": "Internship",
            "intern": "Internship",
        }

        for value in normalized_values:
            if value in mapping:
                return mapping[value]

        return next(iter(normalized_values), None)

    @staticmethod
    def format_salary(raw_job):
        minimum = raw_job.get("salaryMin")
        maximum = raw_job.get("salaryMax")
        currency = raw_job.get("salaryCurrency") or ""
        period = raw_job.get("salaryPeriod") or ""

        if minimum is None and maximum is None:
            return None

        currency_prefix = (
            f"{currency} "
            if currency
            else ""
        )

        if minimum is not None and maximum is not None:
            salary = (
                f"{currency_prefix}"
                f"{minimum:,.0f} - {maximum:,.0f}"
            )
        elif minimum is not None:
            salary = (
                f"From {currency_prefix}"
                f"{minimum:,.0f}"
            )
        else:
            salary = (
                f"Up to {currency_prefix}"
                f"{maximum:,.0f}"
            )

        if period:
            salary = f"{salary} per {period}"

        return salary

    def fetch_jobs(self):
        payload = fetch_json(
            self.feed_url,
            params={"count": 100},
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Jobicy returned an unexpected response."
            )

        jobs = payload.get("jobs", [])

        if not isinstance(jobs, list):
            raise RuntimeError(
                "Jobicy returned invalid jobs data."
            )

        return jobs

    def normalize_job(self, raw_job):
        posting_url = raw_job.get("url")
        industries = raw_job.get("jobIndustry") or []
        job_level = raw_job.get("jobLevel")

        if not isinstance(industries, list):
            industries = [industries]

        departments = [
            str(value).strip()
            for value in industries
            if str(value or "").strip()
        ]

        if job_level:
            departments.append(
                str(job_level).strip()
            )

        description = (
            raw_job.get("jobDescription")
            or raw_job.get("jobExcerpt")
        )

        return {
            "source": self.source_name,
            "external_id": (
                str(raw_job.get("id"))
                if raw_job.get("id") is not None
                else posting_url
            ),
            "company_name": (
                raw_job.get("companyName")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("jobTitle")
                or "Untitled Position"
            ),
            "location": (
                raw_job.get("jobGeo")
                or "Worldwide"
            ),
            "employment_type": (
                self.normalize_employment_type(
                    raw_job.get("jobType")
                )
            ),
            "salary": self.format_salary(raw_job),
            "visa_sponsorship": "Unknown",
            # Jobicy requires keeping the original Jobicy URL
            # and sending applications back to that listing.
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(
                description
            ),
            "departments": departments,
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": raw_job.get("pubDate"),
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
                    "JOBICY CACHE | "
                    f"Using {len(source_class._cached_jobs)} "
                    "cached jobs."
                )

                return list(
                    source_class._cached_jobs
                )

            raw_jobs = self.fetch_jobs()

            normalized_jobs = [
                self.normalize_job(raw_job)
                for raw_job in raw_jobs
                if isinstance(raw_job, dict)
            ]

            normalized_jobs = [
                job
                for job in normalized_jobs
                if job.get("posting_url")
            ]

            source_class._cached_jobs = normalized_jobs
            source_class._cache_fetched_at = datetime.now(
                timezone.utc
            )

            print(
                "JOBICY FEED | "
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
            f"JOBICY SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
