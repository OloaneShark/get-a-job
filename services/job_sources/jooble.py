import os
import re
import threading
from datetime import datetime, timedelta, timezone

import requests

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text
from services.job_sources.job_match_service import job_matches_profile


class JoobleJobSource(BaseJobSource):
    source_name = "Jooble"
    source_type = "jooble"
    requires_company_config = False

    api_root = "https://jooble.org/api"
    results_per_page = 20
    pages_per_query = 2
    cache_duration = timedelta(hours=6)

    _cache_lock = threading.Lock()
    _query_cache = {}

    def __init__(self):
        self._prepared = False
        self._prepared_jobs = []
        self._prepared_stats = {}

    @staticmethod
    def parse_profile_values(value):
        if not value:
            return []

        return [
            item.strip()
            for item in re.split(
                r"[\n,]+",
                str(value),
            )
            if item.strip()
        ]

    @staticmethod
    def normalize_keyword(value):
        text = str(value or "").strip().lower()

        text = text.replace(
            "full-stack",
            "full stack",
        )
        text = text.replace(
            "fullstack",
            "full stack",
        )
        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text

    @classmethod
    def build_keywords(cls, profile):
        values = cls.parse_profile_values(
            getattr(
                profile,
                "keywords",
                None,
            )
        )
        keywords = []
        seen = set()

        for value in values:
            normalized = cls.normalize_keyword(
                value
            )

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            keywords.append(normalized)

        return ", ".join(
            keywords[:20]
        )

    @classmethod
    def build_profile_queries(cls, profile):
        keywords = cls.build_keywords(
            profile
        )

        if not keywords:
            return []

        locations = cls.parse_profile_values(
            getattr(
                profile,
                "locations",
                None,
            )
        )

        if not locations:
            return []

        queries = []
        seen = set()

        for location in locations:
            key = (
                keywords.lower(),
                location.lower(),
            )

            if key in seen:
                continue

            seen.add(key)
            queries.append(
                {
                    "keywords": keywords,
                    "location": location,
                }
            )

        return queries

    @classmethod
    def credentials(cls):
        return str(
            os.getenv(
                "JOOBLE_API_KEY",
                "",
            )
            or ""
        ).strip()

    @classmethod
    def credentials_available(cls):
        return bool(
            cls.credentials()
        )

    @classmethod
    def cache_is_fresh(cls, entry):
        if not entry:
            return False

        fetched_at = entry.get(
            "fetched_at"
        )

        if fetched_at is None:
            return False

        return (
            datetime.now(timezone.utc)
            - fetched_at
        ) < cls.cache_duration

    @staticmethod
    def normalize_employment_type(
        value,
        title,
    ):
        normalized = str(
            value or ""
        ).strip().lower()
        title_text = str(
            title or ""
        ).lower()

        if re.search(
            r"\b(?:intern|internship|co-op|coop)\b",
            title_text,
        ):
            return "Internship"

        mappings = {
            "full-time": "Full-time",
            "full time": "Full-time",
            "fulltime": "Full-time",
            "part-time": "Part-time",
            "part time": "Part-time",
            "parttime": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "temporary": "Temporary",
            "temp": "Temporary",
            "internship": "Internship",
            "intern": "Internship",
        }

        return (
            mappings.get(normalized)
            or value
        )

    @staticmethod
    def normalize_workplace_type(
        title,
        location,
        snippet,
    ):
        text = " ".join(
            [
                str(title or ""),
                str(location or ""),
                str(snippet or ""),
            ]
        ).lower()

        if re.search(
            r"\b(?:fully\s+)?remote\b|"
            r"\bwork\s+from\s+home\b|"
            r"\bwork\s+remotely\b",
            text,
        ):
            return "Remote"

        if re.search(
            r"\bhybrid\b",
            text,
        ):
            return "Hybrid"

        return None

    @staticmethod
    def is_generic_remote_location(value):
        normalized = re.sub(
            r"\s+",
            " ",
            str(value or "").strip().lower(),
        )

        return normalized in {
            "",
            "remote",
            "remote position",
            "remote role",
            "fully remote",
            "work from home",
            "work remotely",
        }

    @classmethod
    def normalize_job(
        cls,
        raw_job,
        query_location=None,
    ):
        posting_url = str(
            raw_job.get("link")
            or ""
        ).strip()

        if not posting_url:
            return None

        title = str(
            raw_job.get("title")
            or "Untitled Position"
        ).strip()
        location = str(
            raw_job.get("location")
            or ""
        ).strip() or None
        snippet = clean_html_text(
            raw_job.get("snippet")
        )
        workplace_type = (
            cls.normalize_workplace_type(
                title,
                location,
                snippet,
            )
        )

        remote_candidate_scope = None
        remote_allowed_locations = []
        location_source = None
        location_confidence = None

        if (
            workplace_type == "Remote"
            and query_location
            and cls.is_generic_remote_location(
                location
            )
        ):
            remote_candidate_scope = (
                "selected_locations"
            )
            remote_allowed_locations = [
                str(query_location).strip()
            ]
            location_source = (
                "jooble_search_scope"
            )
            location_confidence = 0.9

        return {
            "source": cls.source_name,
            "external_id": str(
                raw_job.get("id")
                or posting_url
            ),
            "company_name": str(
                raw_job.get("company")
                or "Unknown Company"
            ).strip(),
            "position_title": title,
            "location": location,
            "location_source": (
                location_source
            ),
            "location_confidence": (
                location_confidence
            ),
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "employment_type": (
                cls.normalize_employment_type(
                    raw_job.get("type"),
                    title,
                )
            ),
            "salary": (
                raw_job.get("salary")
                or None
            ),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": snippet,
            "departments": [],
            "offices": [],
            "is_remote": (
                workplace_type == "Remote"
            ),
            "workplace_type": workplace_type,
            "published_at": (
                raw_job.get("updated")
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @staticmethod
    def merge_remote_scope(
        existing,
        incoming,
    ):
        existing_locations = list(
            existing.get(
                "remote_allowed_locations"
            )
            or []
        )
        incoming_locations = list(
            incoming.get(
                "remote_allowed_locations"
            )
            or []
        )

        merged_locations = []

        for location in (
            existing_locations
            + incoming_locations
        ):
            normalized = str(
                location or ""
            ).strip()

            if (
                normalized
                and normalized
                not in merged_locations
            ):
                merged_locations.append(
                    normalized
                )

        if merged_locations:
            existing[
                "remote_candidate_scope"
            ] = "selected_locations"
            existing[
                "remote_allowed_locations"
            ] = merged_locations

            if not existing.get(
                "location_source"
            ):
                existing[
                    "location_source"
                ] = "jooble_search_scope"

            if existing.get(
                "location_confidence"
            ) is None:
                existing[
                    "location_confidence"
                ] = 0.9

        return existing

    @classmethod
    def request_page(
        cls,
        query,
        page,
    ):
        api_key = cls.credentials()
        endpoint = (
            f"{cls.api_root}/{api_key}"
        )

        payload = {
            "keywords": query[
                "keywords"
            ],
            "location": query[
                "location"
            ],
            "page": str(page),
            "ResultOnPage": (
                cls.results_per_page
            ),
            "companysearch": "false",
        }

        try:
            response = requests.post(
                endpoint,
                json=payload,
                headers={
                    "Accept": (
                        "application/json"
                    ),
                    "Content-Type": (
                        "application/json"
                    ),
                    "User-Agent": (
                        "JobAdInfinitum/1.0"
                    ),
                },
                timeout=30,
            )

        except requests.Timeout:
            raise RuntimeError(
                "Jooble request timed out."
            ) from None

        except requests.RequestException as error:
            raise RuntimeError(
                "Jooble request failed: "
                f"{type(error).__name__}."
            ) from None

        if response.status_code == 403:
            raise RuntimeError(
                "Jooble access denied "
                "(HTTP 403). Check JOOBLE_API_KEY."
            )

        if response.status_code == 404:
            raise RuntimeError(
                "Jooble API endpoint was not found "
                "(HTTP 404)."
            )

        if not response.ok:
            raise RuntimeError(
                "Jooble request failed with "
                f"HTTP {response.status_code}."
            )

        try:
            data = response.json()
        except ValueError:
            raise RuntimeError(
                "Jooble returned invalid JSON."
            ) from None

        if not isinstance(data, dict):
            raise RuntimeError(
                "Jooble returned an unexpected "
                "response."
            )

        jobs = data.get(
            "jobs",
            [],
        )

        if not isinstance(jobs, list):
            raise RuntimeError(
                "Jooble returned invalid jobs data."
            )

        total_count = data.get(
            "totalCount"
        )

        return (
            jobs,
            total_count,
        )

    @classmethod
    def fetch_query(cls, query):
        cache_key = (
            query["keywords"].lower(),
            query["location"].lower(),
        )

        with cls._cache_lock:
            cached = cls._query_cache.get(
                cache_key
            )

            if cls.cache_is_fresh(
                cached
            ):
                return (
                    list(
                        cached["jobs"]
                    ),
                    True,
                    0,
                    cached.get(
                        "total_count"
                    ),
                )

        normalized_jobs = []
        network_requests = 0
        total_count = None

        for page in range(
            1,
            cls.pages_per_query + 1,
        ):
            raw_jobs, page_total = (
                cls.request_page(
                    query,
                    page,
                )
            )
            network_requests += 1

            if total_count is None:
                total_count = page_total

            for raw_job in raw_jobs:
                if not isinstance(
                    raw_job,
                    dict,
                ):
                    continue

                job = cls.normalize_job(
                    raw_job,
                    query_location=(
                        query["location"]
                    ),
                )

                if job is not None:
                    normalized_jobs.append(
                        job
                    )

            if len(raw_jobs) < (
                cls.results_per_page
            ):
                break

        deduplicated = {}

        for job in normalized_jobs:
            key = (
                job.get(
                    "external_id"
                )
                or job.get(
                    "posting_url"
                )
            )

            if key:
                deduplicated[
                    str(key)
                ] = job

        jobs = list(
            deduplicated.values()
        )

        with cls._cache_lock:
            cls._query_cache[
                cache_key
            ] = {
                "fetched_at": (
                    datetime.now(
                        timezone.utc
                    )
                ),
                "jobs": list(jobs),
                "total_count": total_count,
            }

        return (
            jobs,
            False,
            network_requests,
            total_count,
        )

    def prepare(self, profiles):
        self._prepared = True
        self._prepared_jobs = []
        self._prepared_stats = {
            "queries": 0,
            "network_requests": 0,
            "cached_queries": 0,
            "query_errors": 0,
        }

        if not self.credentials_available():
            print(
                "JOOBLE DISABLED | "
                "Set JOOBLE_API_KEY to enable "
                "the source."
            )
            return []

        queries = []
        seen = set()

        for profile in profiles:
            for query in (
                self.build_profile_queries(
                    profile
                )
            ):
                key = (
                    query[
                        "keywords"
                    ].lower(),
                    query[
                        "location"
                    ].lower(),
                )

                if key in seen:
                    continue

                seen.add(key)
                queries.append(query)

        all_jobs = []
        network_requests = 0
        cached_queries = 0
        query_errors = 0

        for query in queries:
            try:
                (
                    jobs,
                    from_cache,
                    requests_made,
                    total_count,
                ) = self.fetch_query(
                    query
                )

            except Exception as error:
                query_errors += 1
                print(
                    "JOOBLE QUERY ERROR | "
                    f"Location: "
                    f"{query['location']} | "
                    f"Error: {error}"
                )
                continue

            network_requests += (
                requests_made
            )

            if from_cache:
                cached_queries += 1

            all_jobs.extend(
                jobs
            )

            print(
                "JOOBLE QUERY | "
                f"Location: "
                f"{query['location']} | "
                f"Keywords: "
                f"{len(self.parse_profile_values(query['keywords']))} | "
                f"Jobs: {len(jobs)} | "
                f"Reported total: "
                f"{total_count if total_count is not None else 'unknown'} | "
                f"Cache: "
                f"{'yes' if from_cache else 'no'}"
            )

        deduplicated = {}

        for job in all_jobs:
            key = (
                job.get(
                    "external_id"
                )
                or job.get(
                    "posting_url"
                )
            )

            if key:
                key = str(key)

                if key in deduplicated:
                    deduplicated[
                        key
                    ] = self.merge_remote_scope(
                        deduplicated[key],
                        job,
                    )
                else:
                    deduplicated[
                        key
                    ] = job

        self._prepared_jobs = list(
            deduplicated.values()
        )
        self._prepared_stats = {
            "queries": len(queries),
            "network_requests": (
                network_requests
            ),
            "cached_queries": (
                cached_queries
            ),
            "query_errors": (
                query_errors
            ),
        }

        print(
            "JOOBLE SHARED FEED | "
            f"Queries: {len(queries)} | "
            f"Network requests: "
            f"{network_requests} | "
            f"Cached queries: "
            f"{cached_queries} | "
            f"Query errors: "
            f"{query_errors} | "
            f"Unique jobs: "
            f"{len(self._prepared_jobs)}"
        )

        return list(
            self._prepared_jobs
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if not self._prepared:
            self.prepare(
                [profile]
            )

        matching_jobs = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "JOOBLE SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: "
            f"{len(self._prepared_jobs)} | "
            f"Matched: "
            f"{len(matching_jobs)}"
        )

        return matching_jobs
