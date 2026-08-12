
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_json,
)
from services.job_sources.job_match_service import (
    collect_match_diagnostics,
    format_match_diagnostics,
    job_matches_profile,
)


class RemoteFirstJobsSource(BaseJobSource):
    source_name = "Remote First Jobs"
    source_type = "remote_first_jobs"
    requires_company_config = False

    feed_url = (
        "https://remotefirstjobs.com/"
        "api/search-jobs"
    )
    tech_categories = (
        "software-development",
        "cybersecurity",
        "data",
        "devops",
        "qa",
    )
    page_size = 100
    max_pages = 5
    cache_duration = timedelta(hours=6)

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
    def normalize_text(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @classmethod
    def normalize_locations(cls, raw_job):
        raw_locations = (
            raw_job.get("locations")
            or []
        )

        if isinstance(raw_locations, str):
            raw_locations = [
                raw_locations
            ]

        if not isinstance(
            raw_locations,
            (list, tuple, set),
        ):
            raw_locations = []

        locations = []

        for value in raw_locations:
            if isinstance(value, dict):
                value = (
                    value.get("name")
                    or value.get("country")
                    or value.get("label")
                    or value.get("value")
                )

            normalized = cls.normalize_text(
                value
            )

            if (
                normalized
                and normalized
                not in locations
            ):
                locations.append(
                    normalized
                )

        return locations[:3]

    @staticmethod
    def normalize_seniority(value):
        normalized = re.sub(
            r"[\s_-]+",
            " ",
            str(value or "").strip().lower(),
        )

        mapping = {
            "intern": "intern",
            "internship": "intern",
            "entry": "entry",
            "entry level": "entry",
            "junior": "junior",
            "mid": "mid",
            "mid level": "mid",
            "middle": "mid",
            "senior": "senior",
            "staff": "staff",
            "principal": "principal",
            "lead": "lead",
            "manager": "manager",
            "director": "manager",
            "executive": "manager",
        }

        return mapping.get(
            normalized
        )

    @classmethod
    def normalize_employment_type(
        cls,
        raw_job,
    ):
        candidates = (
            raw_job.get("employment_type"),
            raw_job.get("job_type"),
            raw_job.get("type"),
        )

        mapping = {
            "full time": "Full-time",
            "fulltime": "Full-time",
            "part time": "Part-time",
            "parttime": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "temporary": "Temporary",
            "temp": "Temporary",
            "intern": "Internship",
            "internship": "Internship",
        }

        for candidate in candidates:
            normalized = re.sub(
                r"[\s_-]+",
                " ",
                str(candidate or "")
                .strip()
                .lower(),
            )

            if normalized in mapping:
                return mapping[
                    normalized
                ]

        title = cls.normalize_text(
            raw_job.get("title")
        ).lower()

        if re.search(
            r"\b(?:intern|internship|co-op|coop)\b",
            title,
        ):
            return "Internship"

        if re.search(
            r"\bcontract(?:or)?\b",
            title,
        ):
            return "Contract"

        if re.search(
            r"\bpart[- ]time\b",
            title,
        ):
            return "Part-time"

        return None

    @classmethod
    def format_salary(cls, raw_job):
        minimum = raw_job.get(
            "salary_min"
        )
        maximum = raw_job.get(
            "salary_max"
        )

        def has_meaningful_value(value):
            if value is None:
                return False

            try:
                return float(value) > 0
            except (
                TypeError,
                ValueError,
            ):
                normalized = (
                    cls.normalize_text(
                        value
                    )
                )

                return normalized not in {
                    "",
                    "0",
                    "0.0",
                    "0.00",
                }

        if not has_meaningful_value(
            minimum
        ):
            minimum = None

        if not has_meaningful_value(
            maximum
        ):
            maximum = None

        if (
            minimum is None
            and maximum is None
        ):
            return None

        currency = cls.normalize_text(
            raw_job.get("salary_currency")
            or raw_job.get("currency")
        )
        period = cls.normalize_text(
            raw_job.get("salary_period")
            or raw_job.get("period")
        )

        def format_value(value):
            if value is None:
                return None

            try:
                number = float(value)
            except (
                TypeError,
                ValueError,
            ):
                return cls.normalize_text(
                    value
                ) or None

            if number.is_integer():
                return f"{int(number):,}"

            return f"{number:,.2f}".rstrip(
                "0"
            ).rstrip(".")

        minimum_text = format_value(
            minimum
        )
        maximum_text = format_value(
            maximum
        )

        prefix = (
            f"{currency} "
            if currency
            else ""
        )

        if (
            minimum_text
            and maximum_text
        ):
            salary = (
                f"{prefix}{minimum_text} - "
                f"{maximum_text}"
            )
        elif minimum_text:
            salary = (
                f"From {prefix}"
                f"{minimum_text}"
            )
        elif maximum_text:
            salary = (
                f"Up to {prefix}"
                f"{maximum_text}"
            )
        else:
            return None

        if period:
            salary = (
                f"{salary} per {period}"
            )

        return salary

    @classmethod
    def parse_datetime(cls, value):
        if not value:
            return None

        text = cls.normalize_text(
            value
        )

        if not text:
            return None

        if text.endswith("Z"):
            text = (
                text[:-1]
                + "+00:00"
            )

        try:
            parsed = (
                datetime.fromisoformat(
                    text
                )
            )
        except ValueError:
            return value

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    @classmethod
    def normalize_job(
        cls,
        raw_job,
    ):
        if not isinstance(
            raw_job,
            dict,
        ):
            return None

        external_id = cls.normalize_text(
            raw_job.get("id")
        )
        posting_url = cls.normalize_text(
            raw_job.get("url")
        )
        title = cls.normalize_text(
            raw_job.get("title")
        )
        company = cls.normalize_text(
            raw_job.get("company_name")
        )

        if (
            not external_id
            or not posting_url
            or not title
            or not company
        ):
            return None

        category = cls.normalize_text(
            raw_job.get("category")
        )
        locations = (
            cls.normalize_locations(
                raw_job
            )
        )

        if locations:
            location = (
                "Remote | "
                + " | ".join(
                    locations
                )
            )
            remote_candidate_scope = (
                "selected_locations"
            )
            location_source = (
                "remote_first_jobs_api"
            )
            location_confidence = 1.0
        else:
            location = "Remote"
            remote_candidate_scope = None
            location_source = (
                "remote_first_jobs_api_unspecified"
            )
            location_confidence = 0.0

        seniority = (
            cls.normalize_seniority(
                raw_job.get("seniority")
            )
        )

        departments = []

        if category:
            departments.append(
                category
            )

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": company,
            "position_title": title,
            "location": location,
            "location_source": (
                location_source
            ),
            "location_confidence": (
                location_confidence
            ),
            "employment_type": (
                cls.normalize_employment_type(
                    raw_job
                )
            ),
            "salary": (
                cls.format_salary(
                    raw_job
                )
            ),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": (
                clean_html_text(
                    raw_job.get(
                        "description"
                    )
                )
            ),
            "departments": departments,
            "offices": locations,
            "is_remote": True,
            "workplace_type": "Remote",
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                locations
            ),
            "published_at": (
                cls.parse_datetime(
                    raw_job.get(
                        "published_at"
                    )
                )
            ),
            "experience_level": seniority,
            "seniority_level": seniority,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_category_jobs(
        cls,
        category,
    ):
        jobs = []
        pages_fetched = 0

        for page in range(
            cls.max_pages
        ):
            payload = fetch_json(
                cls.feed_url,
                params={
                    "category": category,
                    "page": page,
                },
                timeout=30,
            )

            if not isinstance(
                payload,
                dict,
            ):
                raise RuntimeError(
                    "Remote First Jobs returned "
                    "an unexpected response."
                )

            page_jobs = payload.get(
                "jobs"
            )

            if page_jobs is None:
                page_jobs = payload.get(
                    "results"
                )

            if page_jobs is None:
                page_jobs = payload.get(
                    "data"
                )

            if not isinstance(
                page_jobs,
                list,
            ):
                raise RuntimeError(
                    "Remote First Jobs returned "
                    "invalid jobs data."
                )

            pages_fetched += 1

            valid_page_jobs = [
                job
                for job in page_jobs
                if isinstance(
                    job,
                    dict,
                )
            ]

            jobs.extend(
                valid_page_jobs
            )

            jobs_count = payload.get(
                "jobs_count"
            )

            print(
                "REMOTE FIRST JOBS FETCH | "
                f"Category: {category} | "
                f"Page: {page} | "
                f"Page jobs: "
                f"{len(valid_page_jobs)} | "
                f"Collected: {len(jobs)}"
            )

            if not valid_page_jobs:
                break

            if (
                isinstance(
                    jobs_count,
                    int,
                )
                and jobs_count
                < cls.page_size
            ):
                break

            if (
                len(valid_page_jobs)
                < cls.page_size
            ):
                break

        return jobs, pages_fetched

    @classmethod
    def fetch_jobs(cls):
        raw_jobs = []
        category_counts = {}
        pages_fetched = 0
        category_errors = {}

        for category in cls.tech_categories:
            try:
                (
                    category_jobs,
                    category_pages,
                ) = cls.fetch_category_jobs(
                    category
                )
            except Exception as error:
                category_errors[
                    category
                ] = str(error)

                print(
                    "REMOTE FIRST JOBS "
                    "CATEGORY FAILED | "
                    f"Category: {category} | "
                    f"Error: {error}"
                )
                continue

            raw_jobs.extend(
                category_jobs
            )
            category_counts[
                category
            ] = len(
                category_jobs
            )
            pages_fetched += (
                category_pages
            )

        if (
            not raw_jobs
            and category_errors
        ):
            raise RuntimeError(
                "Remote First Jobs failed "
                "for every technical category."
            )

        return (
            raw_jobs,
            category_counts,
            pages_fetched,
            category_errors,
        )

    @classmethod
    def prepare_jobs(cls):
        (
            raw_jobs,
            category_counts,
            pages_fetched,
            category_errors,
        ) = cls.fetch_jobs()

        normalized_jobs = []
        invalid = 0

        for raw_job in raw_jobs:
            job = cls.normalize_job(
                raw_job
            )

            if job is None:
                invalid += 1
                continue

            normalized_jobs.append(
                job
            )

        deduplicated = {}

        for job in normalized_jobs:
            key = str(
                job.get("external_id")
                or job.get(
                    "posting_url"
                )
                or ""
            ).strip()

            if not key:
                invalid += 1
                continue

            deduplicated[
                key
            ] = job

        prepared_jobs = list(
            deduplicated.values()
        )

        stats = {
            "raw": len(raw_jobs),
            "normalized": (
                len(normalized_jobs)
            ),
            "invalid": invalid,
            "unique": len(
                prepared_jobs
            ),
            "pages_fetched": (
                pages_fetched
            ),
            "category_counts": (
                category_counts
            ),
            "category_errors": (
                category_errors
            ),
        }

        print(
            "REMOTE FIRST JOBS FEED | "
            f"Raw: {stats['raw']} | "
            f"Normalized: "
            f"{stats['normalized']} | "
            f"Invalid: {stats['invalid']} | "
            f"Unique: {stats['unique']} | "
            f"Pages: "
            f"{stats['pages_fetched']}"
        )

        return (
            prepared_jobs,
            stats,
        )

    def prepare(
        self,
        profiles,
    ):
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
                    "REMOTE FIRST JOBS CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        (
            jobs,
            stats,
        ) = source_class.prepare_jobs()

        with source_class._cache_lock:
            source_class._cached_jobs = list(
                jobs
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
            jobs
        )
        self._prepared_stats = dict(
            stats
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

        with collect_match_diagnostics() as diagnostics:
            matching_jobs = [
                job
                for job
                in self._prepared_jobs
                if job_matches_profile(
                    job,
                    profile,
                )
            ]

        print(
            "REMOTE FIRST JOBS "
            "SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        if (
            diagnostics["evaluated"] > 0
            and diagnostics["matched"] > 0
        ):
            print(
                format_match_diagnostics(
                    profile.name,
                    self.source_name,
                    diagnostics,
                )
            )

        return matching_jobs
