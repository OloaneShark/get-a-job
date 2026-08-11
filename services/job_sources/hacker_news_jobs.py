
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class HackerNewsJobsSource(BaseJobSource):
    source_name = "Hacker News Jobs"
    source_type = "hacker_news_jobs"
    requires_company_config = False

    api_root = "https://hacker-news.firebaseio.com/v0"
    jobstories_url = f"{api_root}/jobstories.json"
    max_job_ids = 100
    detail_workers = 12
    max_job_age_days = 90
    cache_duration = timedelta(hours=1)

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
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
    def parse_published_at(value):
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None

        try:
            return datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (
            OSError,
            OverflowError,
            ValueError,
        ):
            return None

    @classmethod
    def is_recent(cls, published_at):
        if published_at is None:
            return False

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(
                days=cls.max_job_age_days
            )
        )

        return published_at >= cutoff

    @staticmethod
    def normalize_company_prefix(value):
        text = re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        )

        text = re.sub(
            r"\s*\(\s*YC\s+[^)]*\)\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        text = re.sub(
            r"\s*\[\s*YC\s+[^]]*\]\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

        return text or "Unknown Company"

    @classmethod
    def split_company_and_role(cls, value):
        title = re.sub(
            r"\s+",
            " ",
            clean_html_text(value)
            or "",
        ).strip()

        if not title:
            return (
                "Unknown Company",
                "Untitled Position",
            )

        patterns = (
            r"^(.+?)\s+is\s+hiring\s+(.+)$",
            r"^(.+?)\s+is\s+looking\s+for\s+(.+)$",
            r"^(.+?)\s+hiring\s+(.+)$",
            r"^(.+?)\s+seeks\s+(.+)$",
        )

        for pattern in patterns:
            match = re.match(
                pattern,
                title,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            company = cls.normalize_company_prefix(
                match.group(1)
            )
            role = re.sub(
                r"^[\s:—–-]+|[\s:—–-]+$",
                "",
                match.group(2),
            ).strip()

            if company and role:
                return (
                    company,
                    role,
                )

        generic_match = re.match(
            r"^(.+?)\s+is\s+hiring\s*$",
            title,
            flags=re.IGNORECASE,
        )

        if generic_match:
            return (
                cls.normalize_company_prefix(
                    generic_match.group(1)
                ),
                "Open Technical Roles",
            )

        return (
            "Unknown Company",
            title,
        )

    @staticmethod
    def detect_workplace_type(title, description):
        text = " ".join(
            [
                str(title or ""),
                str(description or ""),
            ]
        ).lower()

        if re.search(r"\bhybrid\b", text):
            return "Hybrid"

        if re.search(
            r"\bremote\b|"
            r"\bwork\s+from\s+home\b|"
            r"\bdistributed\b",
            text,
        ):
            return "Remote"

        return None

    @staticmethod
    def normalize_employment_type(title, description):
        text = " ".join(
            [
                str(title or ""),
                str(description or ""),
            ]
        ).lower()

        if re.search(r"\b(?:intern|internship)\b", text):
            return "Internship"

        if re.search(r"\bpart[- ]time\b", text):
            return "Part-time"

        if re.search(
            r"\bcontract(?:or)?\b|\b1099\b",
            text,
        ):
            return "Contract"

        if re.search(r"\btemporary\b|\btemp\b", text):
            return "Temporary"

        if re.search(r"\bfull[- ]time\b", text):
            return "Full-time"

        return None

    @staticmethod
    def normalize_location(title, description):
        text = "\n".join(
            [
                str(title or ""),
                str(description or ""),
            ]
        )

        patterns = (
            r"\b(?:location|based in)\s*[:\-]\s*([^\n.;|]+)",
            r"\bremote\s+(?:in|from)\s+([^\n.;|]+)",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            location = re.sub(
                r"\s+",
                " ",
                match.group(1),
            ).strip(" ,:-")

            if location and len(location) <= 120:
                return location

        if re.search(
            r"\bremote\b",
            text,
            flags=re.IGNORECASE,
        ):
            return "Remote"

        return None

    @classmethod
    def normalize_job(cls, raw_item):
        if not isinstance(raw_item, dict):
            return None

        if raw_item.get("type") != "job":
            return None

        if raw_item.get("deleted") or raw_item.get("dead"):
            return None

        external_id = str(
            raw_item.get("id")
            or ""
        ).strip()

        if not external_id:
            return None

        raw_title = raw_item.get("title")
        description = clean_html_text(
            raw_item.get("text")
        )

        company_name, position_title = (
            cls.split_company_and_role(
                raw_title
            )
        )

        published_at = cls.parse_published_at(
            raw_item.get("time")
        )

        posting_url = str(
            raw_item.get("url")
            or (
                "https://news.ycombinator.com/"
                f"item?id={external_id}"
            )
        ).strip()

        workplace_type = (
            cls.detect_workplace_type(
                raw_title,
                description,
            )
        )

        location = cls.normalize_location(
            raw_title,
            description,
        )

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": company_name,
            "position_title": position_title,
            "location": location,
            "employment_type": (
                cls.normalize_employment_type(
                    raw_title,
                    description,
                )
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": [],
            "offices": [location] if location else [],
            "is_remote": workplace_type == "Remote",
            "workplace_type": workplace_type,
            "published_at": published_at,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_job_ids(cls):
        data = fetch_json(
            cls.jobstories_url,
            timeout=30,
        )

        if not isinstance(data, list):
            raise RuntimeError(
                "Hacker News returned invalid "
                "job story data."
            )

        job_ids = []

        for value in data:
            try:
                job_id = int(value)
            except (
                TypeError,
                ValueError,
            ):
                continue

            job_ids.append(job_id)

            if len(job_ids) >= cls.max_job_ids:
                break

        return job_ids

    @classmethod
    def fetch_job_item(cls, job_id):
        return fetch_json(
            (
                f"{cls.api_root}/"
                f"item/{job_id}.json"
            ),
            timeout=30,
        )

    @classmethod
    def fetch_jobs(cls):
        job_ids = cls.fetch_job_ids()
        raw_items = []
        request_errors = 0

        with ThreadPoolExecutor(
            max_workers=cls.detail_workers
        ) as executor:
            futures = {
                executor.submit(
                    cls.fetch_job_item,
                    job_id,
                ): job_id
                for job_id in job_ids
            }

            for future in as_completed(
                futures
            ):
                try:
                    raw_item = future.result()
                except Exception:
                    request_errors += 1
                    continue

                if isinstance(raw_item, dict):
                    raw_items.append(raw_item)

        return (
            raw_items,
            len(job_ids),
            request_errors,
        )

    def prepare(self, profiles):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "HACKER NEWS JOBS CACHE | "
                    f"Using {len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        (
            raw_items,
            requested_ids,
            request_errors,
        ) = self.fetch_jobs()

        normalized_jobs = []
        invalid = 0
        old = 0

        for raw_item in raw_items:
            job = self.normalize_job(
                raw_item
            )

            if job is None:
                invalid += 1
                continue

            if not self.is_recent(
                job.get("published_at")
            ):
                old += 1
                continue

            normalized_jobs.append(job)

        deduplicated = {}

        for job in normalized_jobs:
            key = str(
                job.get("external_id")
                or job.get("posting_url")
                or ""
            ).strip()

            if key:
                deduplicated[key] = job

        prepared_jobs = list(
            deduplicated.values()
        )

        stats = {
            "requested_ids": requested_ids,
            "fetched_items": len(raw_items),
            "request_errors": request_errors,
            "invalid": invalid,
            "old": old,
            "unique": len(prepared_jobs),
        }

        with source_class._cache_lock:
            source_class._cached_jobs = list(
                prepared_jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(
                    timezone.utc
                )
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

        remote_count = sum(
            1
            for job in prepared_jobs
            if job.get("workplace_type") == "Remote"
        )

        known_company_count = sum(
            1
            for job in prepared_jobs
            if (
                job.get("company_name")
                and job.get("company_name")
                != "Unknown Company"
            )
        )

        print(
            "HACKER NEWS JOBS SHARED FEED | "
            f"IDs requested: {requested_ids} | "
            f"Items fetched: {len(raw_items)} | "
            f"Request errors: {request_errors} | "
            f"Older than {self.max_job_age_days} days: "
            f"{old} | "
            f"Invalid: {invalid} | "
            f"Unique jobs: {len(prepared_jobs)} | "
            f"Remote detected: {remote_count} | "
            f"Known companies: {known_company_count}"
        )

        return list(
            self._prepared_jobs
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if self._prepared_jobs is None:
            self.prepare(
                [profile]
            )

        matches = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "HACKER NEWS JOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: {len(self._prepared_jobs)} | "
            f"Matched: {len(matches)}"
        )

        return matches
