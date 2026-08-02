
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class RemotiveJobSource(BaseJobSource):
    source_name = "Remotive"
    source_type = "remotive"
    requires_company_config = False

    feed_url = "https://remotive.com/api/remote-jobs"

    # Remotive advises public API users to fetch only a few times per day.
    # Cache the normalized feed for six hours so the application's
    # 15-minute scheduler does not repeatedly call their API.
    cache_duration = timedelta(hours=6)
    _cached_jobs = None
    _cache_fetched_at = None
    _cache_lock = threading.Lock()

    @classmethod
    def cache_is_fresh(cls):
        if cls._cached_jobs is None or cls._cache_fetched_at is None:
            return False

        return (
            datetime.now(timezone.utc) - cls._cache_fetched_at
            < cls.cache_duration
        )

    def fetch_jobs(self):
        payload = fetch_json(self.feed_url)

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Remotive returned an unexpected response."
            )

        jobs = payload.get("jobs", [])

        if not isinstance(jobs, list):
            raise RuntimeError(
                "Remotive returned invalid jobs data."
            )

        return jobs

    def normalize_job(self, raw_job):
        posting_url = raw_job.get("url")
        job_type = str(
            raw_job.get("job_type") or ""
        ).strip().lower()

        employment_type_map = {
            "full_time": "Full-time",
            "part_time": "Part-time",
            "contract": "Contract",
            "freelance": "Contract",
            "internship": "Internship",
            "temporary": "Temporary",
        }

        category = raw_job.get("category")

        return {
            "source": self.source_name,
            "external_id": (
                str(raw_job.get("id"))
                if raw_job.get("id") is not None
                else posting_url
            ),
            "company_name": (
                raw_job.get("company_name")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("title")
                or "Untitled Position"
            ),
            "location": (
                raw_job.get("candidate_required_location")
                or "Worldwide"
            ),
            "employment_type": (
                employment_type_map.get(job_type)
                or raw_job.get("job_type")
            ),
            "salary": raw_job.get("salary"),
            "visa_sponsorship": "Unknown",
            # Remotive requires consumers of its public API to link
            # back to the original Remotive job-listing URL.
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(
                raw_job.get("description")
            ),
            "departments": [category] if category else [],
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": raw_job.get("publication_date"),
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
                    "REMOTIVE CACHE | "
                    f"Using {len(source_class._cached_jobs)} "
                    "cached jobs."
                )
                return list(source_class._cached_jobs)

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
                "REMOTIVE FEED | "
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
            f"REMOTIVE SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
