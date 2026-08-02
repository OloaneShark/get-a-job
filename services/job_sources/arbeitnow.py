
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class ArbeitnowJobSource(BaseJobSource):
    source_name = "Arbeitnow"
    source_type = "arbeitnow"
    requires_company_config = False

    feed_url = "https://www.arbeitnow.com/api/job-board-api"

    # Cache the public feed so the 15-minute scheduler does not
    # repeatedly request the same pages throughout the day.
    cache_duration = timedelta(hours=6)
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
    def normalize_employment_type(values):
        if not values:
            return None

        if not isinstance(values, list):
            values = [values]

        normalized_values = [
            str(value or "")
            .strip()
            .lower()
            .replace("_", "-")
            for value in values
            if str(value or "").strip()
        ]

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
            "working student": "Part-time",
        }

        for value in normalized_values:
            if value in mapping:
                return mapping[value]

        return normalized_values[0] if normalized_values else None

    @staticmethod
    def normalize_created_at(value):
        if value is None:
            return None

        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return str(value)

        return datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ).isoformat()

    def fetch_jobs(self):
        collected_jobs = []
        seen_keys = set()

        for page_number in range(
            1,
            self.max_pages_per_refresh + 1,
        ):
            payload = fetch_json(
                self.feed_url,
                params={"page": page_number},
            )

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Arbeitnow returned an unexpected response."
                )

            page_jobs = payload.get("data", [])

            if not isinstance(page_jobs, list):
                raise RuntimeError(
                    "Arbeitnow returned invalid jobs data."
                )

            if not page_jobs:
                break

            added_count = 0

            for raw_job in page_jobs:
                if not isinstance(raw_job, dict):
                    continue

                deduplication_key = (
                    str(raw_job.get("slug") or "").strip()
                    or str(raw_job.get("url") or "").strip()
                )

                if not deduplication_key:
                    continue

                if deduplication_key in seen_keys:
                    continue

                seen_keys.add(deduplication_key)
                collected_jobs.append(raw_job)
                added_count += 1

            print(
                "ARBEITNOW FETCH PROGRESS | "
                f"Page: {page_number} | "
                f"New jobs: {added_count} | "
                f"Jobs collected: {len(collected_jobs)}"
            )

            # Stop safely if the API ignores the page parameter
            # or starts returning the same page repeatedly.
            if added_count == 0:
                break

        return collected_jobs

    def normalize_job(self, raw_job):
        posting_url = raw_job.get("url")
        tags = raw_job.get("tags") or []

        if not isinstance(tags, list):
            tags = [tags]

        departments = [
            str(value).strip()
            for value in tags
            if str(value or "").strip()
        ]

        is_remote = bool(raw_job.get("remote"))
        location = (
            raw_job.get("location")
            or ("Remote" if is_remote else "Germany")
        )

        return {
            "source": self.source_name,
            "external_id": (
                str(raw_job.get("slug"))
                if raw_job.get("slug")
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
            "location": location,
            "employment_type": (
                self.normalize_employment_type(
                    raw_job.get("job_types")
                )
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(
                raw_job.get("description")
            ),
            "departments": departments,
            "offices": [],
            "is_remote": is_remote,
            "workplace_type": (
                "Remote"
                if is_remote
                else "On-site"
            ),
            "published_at": self.normalize_created_at(
                raw_job.get("created_at")
            ),
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
                    "ARBEITNOW CACHE | "
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
            source_class._cache_fetched_at = datetime.now(
                timezone.utc
            )

            print(
                "ARBEITNOW FEED | "
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
            f"ARBEITNOW SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
