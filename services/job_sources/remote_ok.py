
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile
from services.job_sources.remote_ok_crawler import (
    crawl_recent_remote_ok_jobs,
)


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


def safe_terminal_text(value):
    text = str(value or "")
    encoding = (
        getattr(sys.stdout, "encoding", None)
        or "utf-8"
    )

    return text.encode(
        encoding,
        errors="backslashreplace",
    ).decode(
        encoding,
        errors="replace",
    )


def safe_print(message):
    print(safe_terminal_text(message))


class RemoteOKJobSource(BaseJobSource):
    source_name = "Remote OK"
    source_type = "remote_ok"
    requires_company_config = False

    feed_url = "https://remoteok.com/api"

    # Remote OK's sitemap is expensive to discover. Build one
    # shared candidate feed for all active profiles, then let the
    # normal profile matcher filter that feed for each user profile.
    cache_duration = timedelta(hours=1)
    pages_per_profile = 20
    maximum_shared_pages = 100

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cache_signature = None
    _cached_stats = None

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

    @classmethod
    def cache_is_fresh(cls):
        return (
            cls._cached_jobs is not None
            and cls._cache_fetched_at is not None
            and (
                datetime.now(timezone.utc)
                - cls._cache_fetched_at
            ) < cls.cache_duration
        )

    @staticmethod
    def parse_profile_values(value):
        if not value:
            return []

        return [
            item.strip().lower()
            for item in re.split(
                r"[\n,]+",
                str(value),
            )
            if item.strip()
        ]

    @classmethod
    def build_discovery_profile(cls, profiles):
        profiles = [
            profile
            for profile in profiles
            if profile is not None
        ]

        keywords = set()
        experience_levels = set()

        for profile in profiles:
            keywords.update(
                cls.parse_profile_values(
                    getattr(
                        profile,
                        "keywords",
                        None,
                    )
                )
            )
            experience_levels.update(
                cls.parse_profile_values(
                    getattr(
                        profile,
                        "experience_levels",
                        None,
                    )
                )
            )

        profile_count = max(
            1,
            len(profiles),
        )
        max_job_pages = min(
            cls.maximum_shared_pages,
            cls.pages_per_profile
            * profile_count,
        )

        signature = (
            tuple(sorted(keywords)),
            tuple(sorted(experience_levels)),
            max_job_pages,
        )

        discovery_profile = SimpleNamespace(
            name="Shared active profiles",
            keywords=",".join(
                sorted(keywords)
            ),
            experience_levels=",".join(
                sorted(experience_levels)
            ),
            remote_scope="any",
            visa_preference="any",
        )

        return (
            discovery_profile,
            signature,
            max_job_pages,
        )

    @staticmethod
    def deduplicate_jobs(jobs):
        deduplicated = {}

        for job in jobs:
            external_id = str(
                job.get("external_id")
                or ""
            ).strip()
            posting_url = str(
                job.get("posting_url")
                or ""
            ).strip()
            deduplication_key = (
                external_id
                or posting_url
            )

            if not deduplication_key:
                continue

            deduplicated[
                deduplication_key
            ] = job

        return list(
            deduplicated.values()
        )

    @staticmethod
    def is_plausible_job(job):
        title = str(
            job.get("position_title")
            or ""
        ).strip()
        company = str(
            job.get("company_name")
            or ""
        ).strip()
        posting_url = str(
            job.get("posting_url")
            or ""
        ).strip()

        if not title or not company or not posting_url:
            return False

        rejected_titles = {
            "join our team",
            "join us",
            "come and join us",
            "apply for employment",
            "job title",
            "sample job",
            "heading",
            "life",
            "no",
        }

        if title.lower() in rejected_titles:
            return False

        if len(title) < 4:
            return False

        suspicious_phrases = {
            "how do i",
            "how keep your",
            "the mino earrings",
            "the introspect",
            "i want all the money",
            "job hunting indecision",
            "we don't currently have",
            "https ",
        }

        lowered_title = title.lower()

        if any(
            phrase in lowered_title
            for phrase in suspicious_phrases
        ):
            return False

        return True

    def fetch_jobs(self):
        payload = fetch_json(
            self.feed_url
        )

        if not isinstance(payload, list):
            raise RuntimeError(
                "Remote OK returned an unexpected response."
            )

        jobs = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            # Remote OK commonly places metadata first.
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

        location = (
            raw_job.get("location")
            or "Remote"
        )
        salary_min = raw_job.get(
            "salary_min"
        )
        salary_max = raw_job.get(
            "salary_max"
        )
        salary = None

        if salary_min and salary_max:
            salary = (
                f"${salary_min:,} - "
                f"${salary_max:,}"
            )
        elif salary_min:
            salary = (
                f"From ${salary_min:,}"
            )
        elif salary_max:
            salary = (
                f"Up to ${salary_max:,}"
            )

        return {
            "source": self.source_name,
            "external_id": str(
                raw_job.get("id")
            ),
            "company_name": str(
                raw_job.get("company")
                or "Unknown Company"
            ),
            "position_title": str(
                raw_job.get("position")
                or "Untitled Position"
            ),
            "location": str(location),
            "employment_type": "Full-time",
            # Remote OK normally does not provide
            # dependable sponsorship information.
            "visa_sponsorship": "unknown",
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

    def prepare(self, profiles):
        (
            discovery_profile,
            signature,
            max_job_pages,
        ) = self.build_discovery_profile(
            profiles
        )
        source_class = type(self)

        with source_class._cache_lock:
            if (
                source_class.cache_is_fresh()
                and source_class._cache_signature
                == signature
            ):
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                safe_print(
                    "REMOTE OK CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "shared normalized jobs."
                )
                return list(
                    self._prepared_jobs
                )

            api_jobs = []
            api_error = None

            try:
                raw_jobs = self.fetch_jobs()
                api_jobs = [
                    self.normalize_job(
                        raw_job
                    )
                    for raw_job in raw_jobs
                ]
            except Exception as error:
                api_error = error

                safe_print(
                    "REMOTE OK API WARNING | "
                    "API unavailable, continuing "
                    "with crawler | "
                    f"Error: {error}"
                )

            # Crawl once for the union of all active profile
            # keywords and experience levels.
            crawled_jobs = (
                crawl_recent_remote_ok_jobs(
                    profile=discovery_profile,
                    max_age_days=30,
                    max_job_pages=max_job_pages,
                )
            )

            if not api_jobs and not crawled_jobs:
                if api_error is not None:
                    raise RuntimeError(
                        "Remote OK API failed and "
                        "the crawler returned no jobs."
                    ) from api_error

                self._prepared_jobs = []
                self._prepared_stats = {
                    "api_count": 0,
                    "crawled_count": 0,
                    "invalid_count": 0,
                    "api_unavailable": False,
                    "max_job_pages": (
                        max_job_pages
                    ),
                }
                return []

            combined_jobs = (
                self.deduplicate_jobs(
                    api_jobs
                    + crawled_jobs
                )
            )
            prepared_jobs = []
            invalid_record_count = 0

            for job in combined_jobs:
                if not self.is_plausible_job(
                    job
                ):
                    invalid_record_count += 1

                    if source_debug_enabled():
                        safe_print(
                            "REMOTE OK INVALID RECORD | "
                            f"Title: "
                            f"{job.get('position_title')} | "
                            f"Company: "
                            f"{job.get('company_name')}"
                        )

                    continue

                prepared_jobs.append(job)

            stats = {
                "api_count": len(api_jobs),
                "crawled_count": (
                    len(crawled_jobs)
                ),
                "invalid_count": (
                    invalid_record_count
                ),
                "api_unavailable": (
                    api_error is not None
                ),
                "max_job_pages": (
                    max_job_pages
                ),
            }

            source_class._cached_jobs = list(
                prepared_jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(timezone.utc)
            )
            source_class._cache_signature = (
                signature
            )
            source_class._cached_stats = dict(
                stats
            )

            self._prepared_jobs = list(
                prepared_jobs
            )
            self._prepared_stats = dict(
                stats
            )

            safe_print(
                "REMOTE OK SHARED FEED | "
                f"Profiles combined: "
                f"{max(1, len(profiles))} | "
                f"API: {len(api_jobs)} | "
                f"Crawled: "
                f"{len(crawled_jobs)} | "
                f"Combined valid: "
                f"{len(prepared_jobs)} | "
                f"Invalid skipped: "
                f"{invalid_record_count} | "
                f"Page limit: "
                f"{max_job_pages}"
            )

            return list(
                prepared_jobs
            )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if self._prepared_jobs is None:
            self.prepare([profile])

        all_jobs = list(
            self._prepared_jobs
            or []
        )
        stats = dict(
            self._prepared_stats
            or {}
        )
        matching_jobs = []

        safe_print(
            "REMOTE OK SEARCH | "
            f"Profile: {profile.name} | "
            f"Shared feed: "
            f"{len(all_jobs)} | "
            f"API: "
            f"{stats.get('api_count', 0)} | "
            f"Crawled: "
            f"{stats.get('crawled_count', 0)} | "
            f"Experience: "
            f"{profile.experience_levels or 'any'} | "
            f"Remote scope: "
            f"{profile.remote_scope or 'any'} | "
            f"Visa: "
            f"{profile.visa_preference or 'any'}"
        )

        for job in all_jobs:
            if not job_matches_profile(
                job,
                profile,
            ):
                continue

            matching_jobs.append(job)

        safe_print(
            "REMOTE OK SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: "
            f"{len(matching_jobs)} | "
            f"Invalid records skipped during "
            f"shared preparation: "
            f"{stats.get('invalid_count', 0)}"
        )

        return matching_jobs
