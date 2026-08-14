
import os
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_response
from services.job_sources.job_match_service import job_matches_profile


class AIDevJobsSource(BaseJobSource):
    source_name = "AI Dev Jobs"
    source_type = "ai_dev_jobs"
    requires_company_config = False

    feed_url = "https://aidevboard.com/api/v1/jobs"
    page_size = 50
    max_requests_per_prepare = 60
    rate_limit_reserve = 50
    max_pages_per_query = 3
    cache_duration = timedelta(hours=1)

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None
    _cached_signature = None

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

    @classmethod
    def cache_is_fresh(cls):
        return (
            cls._cached_jobs is not None
            and cls._cache_fetched_at is not None
            and datetime.now(timezone.utc) - cls._cache_fetched_at
            < cls.cache_duration
        )

    @staticmethod
    def normalize_text(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def canonicalize_query(
        cls,
        value,
    ):
        query = cls.normalize_text(value).lower()
        query = re.sub(r"[-_/]+", " ", query)
        query = re.sub(r"\s+", " ", query).strip()

        aliases = {
            "fullstack": "full stack",
            "frontend": "front end",
            "backend": "back end",
        }

        return aliases.get(query, query)

    @classmethod
    def query_identity(
        cls,
        value,
    ):
        canonical = cls.canonicalize_query(value)
        return re.sub(r"[^a-z0-9]+", "", canonical)

    @classmethod
    def parse_profile_keywords(cls, profile):
        raw_keywords = getattr(profile, "keywords", "")
        return [
            cls.normalize_text(keyword)
            for keyword in re.split(r"[\n,]+", raw_keywords or "")
            if cls.normalize_text(keyword)
        ]

    @classmethod
    def build_queries(cls, profiles):
        queries = []
        seen = set()

        for profile in profiles:
            for keyword in cls.parse_profile_keywords(profile):
                query = cls.canonicalize_query(keyword)
                key = cls.query_identity(query)

                if not query or not key or key in seen:
                    continue

                seen.add(key)
                queries.append(query)

        return queries or [None]

    @staticmethod
    def header_integer(response, name):
        value = response.headers.get(name)
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def request_headers(cls):
        api_key = os.getenv("AI_DEV_JOBS_API_KEY", "").strip()
        if not api_key:
            return None
        return {"X-API-Key": api_key}

    @classmethod
    def normalize_employment_type(cls, value):
        normalized = re.sub(
            r"[\s_-]+",
            " ",
            cls.normalize_text(value).lower(),
        )
        mapping = {
            "full time": "Full-time",
            "fulltime": "Full-time",
            "part time": "Part-time",
            "parttime": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "freelance": "Freelance",
            "intern": "Internship",
            "internship": "Internship",
            "temporary": "Temporary",
            "temp": "Temporary",
        }
        return mapping.get(normalized)

    @classmethod
    def normalize_experience_level(cls, value):
        normalized = re.sub(
            r"[\s_-]+",
            " ",
            cls.normalize_text(value).lower(),
        )
        mapping = {
            "intern": "intern",
            "internship": "intern",
            "entry": "entry",
            "entry level": "entry",
            "new grad": "entry",
            "new graduate": "entry",
            "junior": "junior",
            "mid": "mid",
            "mid level": "mid",
            "senior": "senior",
            "staff": "staff",
            "principal": "principal",
            "lead": "lead",
            "manager": "manager",
            "director": "manager",
        }
        return mapping.get(normalized)

    @classmethod
    def normalize_workplace(cls, value):
        normalized = re.sub(
            r"[\s_-]+",
            " ",
            cls.normalize_text(value).lower(),
        )
        mapping = {
            "remote": "Remote",
            "hybrid": "Hybrid",
            "onsite": "On-site",
            "on site": "On-site",
        }
        return mapping.get(normalized)

    @classmethod
    def format_salary(cls, raw_job):
        def number(value):
            if value is None:
                return None
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return None
            return parsed if parsed > 0 else None

        minimum = number(raw_job.get("salary_min"))
        maximum = number(raw_job.get("salary_max"))

        if minimum is None and maximum is None:
            return None

        def money(value):
            if value is None:
                return None
            if value.is_integer():
                return f"${int(value):,}"
            return f"${value:,.2f}".rstrip("0").rstrip(".")

        minimum_text = money(minimum)
        maximum_text = money(maximum)

        if minimum_text and maximum_text:
            return f"{minimum_text} - {maximum_text} / year"
        if minimum_text:
            return f"From {minimum_text} / year"
        return f"Up to {maximum_text} / year"

    @classmethod
    def parse_datetime(cls, value):
        if not value:
            return None

        text = cls.normalize_text(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return value

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    @classmethod
    def normalize_job(cls, raw_job):
        if not isinstance(raw_job, dict):
            return None

        external_id = cls.normalize_text(raw_job.get("id"))
        title = cls.normalize_text(raw_job.get("title"))
        company = cls.normalize_text(raw_job.get("company_name"))
        source_url = cls.normalize_text(raw_job.get("url"))
        apply_url = cls.normalize_text(raw_job.get("apply_url"))
        posting_url = apply_url or source_url

        if not external_id or not title or not company or not posting_url:
            return None

        location = cls.normalize_text(raw_job.get("location"))
        workplace_type = cls.normalize_workplace(raw_job.get("workplace"))
        remote_scope = cls.normalize_text(raw_job.get("remote_scope")).lower()
        is_remote = workplace_type == "Remote"

        remote_candidate_scope = None
        remote_allowed_locations = []

        if is_remote:
            if remote_scope in {"global", "worldwide"}:
                remote_candidate_scope = "worldwide"
                if not location:
                    location = "Remote Worldwide"
            elif remote_scope in {"restricted", "selected_locations"}:
                remote_candidate_scope = "selected_locations"
                if location:
                    remote_allowed_locations = [location]

            if not location:
                location = "Remote"

        if not location:
            location = "Unknown"

        if is_remote and remote_candidate_scope is None:
            location_confidence = 0.0
            location_source = "ai_dev_jobs_api_remote_scope_unspecified"
        else:
            location_confidence = 1.0
            location_source = "ai_dev_jobs_api"

        experience_level = cls.normalize_experience_level(
            raw_job.get("experience_level")
        )

        raw_tags = raw_job.get("tags")
        if not isinstance(raw_tags, list):
            raw_tags = []

        tags = [
            cls.normalize_text(tag)
            for tag in raw_tags
            if cls.normalize_text(tag)
        ]

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": company,
            "position_title": title,
            "location": location,
            "location_source": location_source,
            "location_confidence": location_confidence,
            "employment_type": cls.normalize_employment_type(
                raw_job.get("job_type")
            ),
            "salary": cls.format_salary(raw_job),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": apply_url or posting_url,
            "job_description": clean_html_text(raw_job.get("description")),
            "is_remote": is_remote,
            "workplace_type": workplace_type,
            "remote_candidate_scope": remote_candidate_scope,
            "remote_allowed_locations": remote_allowed_locations,
            "published_at": cls.parse_datetime(raw_job.get("published_at")),
            "experience_level": experience_level,
            "seniority_level": experience_level,
            "tags": tags,
            "departments": tags,
            "source_listing_url": source_url,
            "quality_score": raw_job.get("quality_score"),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_query_jobs(cls, query, max_pages, request_state):
        jobs = []
        pages_fetched = 0

        for page in range(1, max_pages + 1):
            if request_state["used"] >= cls.max_requests_per_prepare:
                break

            remaining = request_state.get("remaining")
            if (
                remaining is not None
                and remaining <= cls.rate_limit_reserve
            ):
                print(
                    "AI DEV JOBS RATE LIMIT | "
                    f"Stopping with {remaining} requests remaining."
                )
                break

            params = {
                "page": page,
                "limit": cls.page_size,
            }
            if query:
                params["q"] = query

            response = fetch_response(
                cls.feed_url,
                params=params,
                headers=cls.request_headers(),
                timeout=30,
            )

            request_state["used"] += 1
            request_state["tier"] = (
                response.headers.get("X-API-Tier")
                or request_state.get("tier")
            )
            request_state["limit"] = (
                cls.header_integer(response, "X-RateLimit-Limit")
                or request_state.get("limit")
            )

            current_remaining = cls.header_integer(
                response,
                "X-RateLimit-Remaining",
            )
            if current_remaining is not None:
                request_state["remaining"] = current_remaining

            request_state["reset"] = (
                cls.header_integer(response, "X-RateLimit-Reset")
                or request_state.get("reset")
            )

            try:
                payload = response.json()
            except ValueError as error:
                raise RuntimeError(
                    "AI Dev Jobs returned invalid JSON."
                ) from error

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "AI Dev Jobs returned an unexpected response."
                )

            page_jobs = payload.get("jobs")
            if not isinstance(page_jobs, list):
                raise RuntimeError(
                    "AI Dev Jobs returned invalid jobs data."
                )

            valid_page_jobs = [
                job for job in page_jobs if isinstance(job, dict)
            ]
            jobs.extend(valid_page_jobs)
            pages_fetched += 1

            print(
                "AI DEV JOBS FETCH | "
                f"Query: {query or 'all'} | "
                f"Page: {page} | "
                f"Page jobs: {len(valid_page_jobs)} | "
                f"Collected: {len(jobs)} | "
                f"Rate remaining: {request_state.get('remaining')}"
            )

            if not valid_page_jobs:
                break
            if payload.get("has_next") is False:
                break

            total_pages = payload.get("total_pages")
            if isinstance(total_pages, int) and page >= total_pages:
                break

        return jobs, pages_fetched

    @classmethod
    def prepare_jobs(cls, profiles):
        queries = cls.build_queries(profiles)

        if len(queries) > cls.max_requests_per_prepare:
            queries = queries[:cls.max_requests_per_prepare]
            print(
                "AI DEV JOBS QUERY LIMIT | "
                f"Query list limited to {len(queries)}."
            )

        pages_per_query = max(
            1,
            min(
                cls.max_pages_per_query,
                cls.max_requests_per_prepare // len(queries),
            ),
        )

        request_state = {
            "used": 0,
            "remaining": None,
            "limit": None,
            "reset": None,
            "tier": None,
        }

        raw_jobs = []
        query_counts = {}
        query_errors = {}

        for query in queries:
            try:
                query_jobs, pages_fetched = cls.fetch_query_jobs(
                    query,
                    pages_per_query,
                    request_state,
                )
            except Exception as error:
                query_errors[query or "all"] = str(error)
                print(
                    "AI DEV JOBS QUERY FAILED | "
                    f"Query: {query or 'all'} | "
                    f"Error: {error}"
                )
                continue

            raw_jobs.extend(query_jobs)
            query_counts[query or "all"] = {
                "jobs": len(query_jobs),
                "pages": pages_fetched,
            }

            remaining = request_state.get("remaining")
            if (
                remaining is not None
                and remaining <= cls.rate_limit_reserve
            ):
                break

            if request_state["used"] >= cls.max_requests_per_prepare:
                break

        if not raw_jobs and query_errors:
            raise RuntimeError(
                "AI Dev Jobs failed for every attempted query."
            )

        normalized_jobs = []
        invalid = 0

        for raw_job in raw_jobs:
            job = cls.normalize_job(raw_job)
            if job is None:
                invalid += 1
                continue
            normalized_jobs.append(job)

        deduplicated = {}
        for job in normalized_jobs:
            key = str(
                job.get("external_id")
                or job.get("posting_url")
                or ""
            ).strip()

            if not key:
                invalid += 1
                continue

            deduplicated[key] = job

        prepared_jobs = list(deduplicated.values())

        stats = {
            "queries": len(queries),
            "raw": len(raw_jobs),
            "normalized": len(normalized_jobs),
            "invalid": invalid,
            "unique": len(prepared_jobs),
            "requests": request_state["used"],
            "api_tier": request_state.get("tier"),
            "rate_limit": request_state.get("limit"),
            "rate_remaining": request_state.get("remaining"),
            "rate_reset": request_state.get("reset"),
            "query_counts": query_counts,
            "query_errors": query_errors,
        }

        print(
            "AI DEV JOBS FEED | "
            f"Queries: {stats['queries']} | "
            f"Raw: {stats['raw']} | "
            f"Normalized: {stats['normalized']} | "
            f"Invalid: {stats['invalid']} | "
            f"Unique: {stats['unique']} | "
            f"Requests: {stats['requests']} | "
            f"Tier: {stats['api_tier']} | "
            f"Rate remaining: {stats['rate_remaining']}"
        )

        return prepared_jobs, stats

    def prepare(self, profiles):
        source_class = type(self)
        queries = source_class.build_queries(profiles)

        signature = tuple(
            sorted(
                str(query or "").strip().casefold()
                for query in queries
            )
        )

        with source_class._cache_lock:
            if (
                source_class.cache_is_fresh()
                and source_class._cached_signature == signature
            ):
                self._prepared_jobs = list(source_class._cached_jobs)
                self._prepared_stats = dict(
                    source_class._cached_stats or {}
                )

                print(
                    "AI DEV JOBS CACHE | "
                    f"Using {len(self._prepared_jobs)} normalized jobs."
                )

                return list(self._prepared_jobs)

        jobs, stats = source_class.prepare_jobs(profiles)

        with source_class._cache_lock:
            source_class._cached_jobs = list(jobs)
            source_class._cache_fetched_at = datetime.now(timezone.utc)
            source_class._cached_stats = dict(stats)
            source_class._cached_signature = signature

        self._prepared_jobs = list(jobs)
        self._prepared_stats = dict(stats)

        return list(self._prepared_jobs)

    def search(self, profile, source_config=None):
        if self._prepared_jobs is None:
            self.prepare([profile])

        matching_jobs = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(job, profile)
        ]

        print(
            "AI DEV JOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
