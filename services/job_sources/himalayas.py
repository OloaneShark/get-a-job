
import threading
import time
import re
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import (
    job_matches_profile,
    parse_profile_locations,
    selected_location_country,
)
from services.job_sources.discovery.himalayas_discovery import (
    direct_application_url,
    extract_supported_source_records,
)


class HimalayasJobSource(BaseJobSource):
    source_name = "Himalayas"
    source_type = "himalayas"
    requires_company_config = False

    feed_url = "https://himalayas.app/jobs/api"
    search_url = "https://himalayas.app/jobs/api/search"

    # Himalayas refreshes its public API data every 24 hours,
    # so there is no benefit to fetching it every 15 minutes.
    cache_duration = timedelta(hours=24)
    page_limit = 20
    max_pages_per_refresh = 10
    max_search_queries_per_refresh = 18
    max_search_queries_per_profile = 6
    max_pages_per_search_query = 3
    request_delay_seconds = 0.1

    _cached_jobs = None
    _cache_fetched_at = None
    _cache_signature = None
    _cache_lock = threading.Lock()

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

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
    def location_restriction_names(raw_job):
        restrictions = raw_job.get("locationRestrictions") or []
        location_names = []

        for restriction in restrictions:
            if isinstance(restriction, dict):
                location_name = (
                    restriction.get("name")
                    or restriction.get("alpha2")
                    or restriction.get("slug")
                )
            else:
                location_name = restriction

            normalized_name = str(
                location_name or ""
            ).strip()

            if (
                normalized_name
                and normalized_name not in location_names
            ):
                location_names.append(normalized_name)

        return location_names

    @classmethod
    def format_location(cls, raw_job):
        location_names = cls.location_restriction_names(
            raw_job
        )

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

    @staticmethod
    def profile_values(value):
        return [
            item.strip()
            for item in re.split(
                r"[\r\n,]+",
                str(value or ""),
            )
            if item.strip()
        ]

    @classmethod
    def profile_keywords(cls, profile):
        terms = []
        seen = set()

        for value in cls.profile_values(
            getattr(profile, "keywords", "")
        ):
            normalized = " ".join(
                value.split()
            )
            key = normalized.casefold()

            if not normalized or key in seen:
                continue

            seen.add(key)
            terms.append(normalized)

        return terms

    @classmethod
    def profile_countries(cls, profile):
        countries = []
        seen = set()

        for location in parse_profile_locations(
            getattr(profile, "locations", "")
        ):
            country = selected_location_country(
                location
            )

            if not country:
                continue

            key = country.casefold()

            if key in seen:
                continue

            seen.add(key)
            countries.append(country)

        return countries

    @classmethod
    def profile_seniority(cls, profile):
        mapping = {
            "entry": "Entry-level",
            "entry level": "Entry-level",
            "entry-level": "Entry-level",
            "mid": "Mid-level",
            "mid level": "Mid-level",
            "mid-level": "Mid-level",
            "senior": "Senior",
            "manager": "Manager",
            "director": "Director",
            "executive": "Executive",
        }

        return list(dict.fromkeys(
            mapping[normalized]
            for normalized in (
                value.casefold()
                for value in cls.profile_values(
                    getattr(
                        profile,
                        "experience_levels",
                        "",
                    )
                )
            )
            if normalized in mapping
        ))

    @classmethod
    def profile_employment_types(cls, profile):
        mapping = {
            "full time": "Full Time",
            "full-time": "Full Time",
            "part time": "Part Time",
            "part-time": "Part Time",
            "contract": "Contractor",
            "contractor": "Contractor",
            "temporary": "Temporary",
            "intern": "Intern",
            "internship": "Intern",
            "volunteer": "Volunteer",
            "other": "Other",
        }

        return list(dict.fromkeys(
            mapping[normalized]
            for normalized in (
                value.casefold()
                for value in cls.profile_values(
                    getattr(
                        profile,
                        "employment_types",
                        "",
                    )
                )
            )
            if normalized in mapping
        ))

    @classmethod
    def build_search_queries(cls, profiles):
        query_groups = []

        for profile in profiles or []:
            profile_queries = []
            profile_seen = set()
            terms = cls.profile_keywords(
                profile
            ) or [""]
            countries = cls.profile_countries(
                profile
            )
            remote_scope = str(
                getattr(
                    profile,
                    "remote_scope",
                    "any",
                )
                or "any"
            ).strip().lower()
            seniority = cls.profile_seniority(
                profile
            )
            employment_types = (
                cls.profile_employment_types(
                    profile
                )
            )

            if remote_scope == "worldwide":
                scopes = [
                    {"worldwide": "true"}
                ]
            elif countries:
                scopes = [
                    {"country": country}
                    for country in countries
                ]
            else:
                scopes = [{}]

            for term in terms:
                for scope in scopes:
                    if (
                        len(profile_queries)
                        >= cls.max_search_queries_per_profile
                    ):
                        break

                    query = {
                        "sort": "recent",
                        **scope,
                    }

                    if term:
                        query["q"] = term

                    if seniority:
                        query["seniority"] = (
                            ",".join(seniority)
                        )

                    if employment_types:
                        query["employment_type"] = (
                            ",".join(
                                employment_types
                            )
                        )

                    key = tuple(sorted(
                        query.items()
                    ))

                    if key in profile_seen:
                        continue

                    profile_seen.add(key)
                    profile_queries.append(query)

                if (
                    len(profile_queries)
                    >= cls.max_search_queries_per_profile
                ):
                    break

            if profile_queries:
                query_groups.append(
                    profile_queries
                )

        queries = []
        seen = set()
        maximum_group_size = max(
            (
                len(group)
                for group in query_groups
            ),
            default=0,
        )

        for query_index in range(
            maximum_group_size
        ):
            for group in query_groups:
                if query_index >= len(group):
                    continue

                query = group[query_index]
                key = tuple(sorted(
                    query.items()
                ))

                if key in seen:
                    continue

                seen.add(key)
                queries.append(query)

        if (
            len(queries)
            > cls.max_search_queries_per_refresh
        ):
            print(
                "HIMALAYAS QUERY LIMIT | "
                f"Prepared: {len(queries)} | "
                "Using first "
                f"{cls.max_search_queries_per_refresh}."
            )

            queries = queries[
                :cls.max_search_queries_per_refresh
            ]

        return queries

    def fetch_search_jobs(self, queries):
        jobs_by_id = {}
        requests_made = 0

        for query_number, query in enumerate(
            queries,
            start=1,
        ):
            total_count = None
            query_job_count = 0

            for page_number in range(
                1,
                self.max_pages_per_search_query
                + 1,
            ):
                payload = fetch_json(
                    self.search_url,
                    params={
                        **query,
                        "page": page_number,
                    },
                )
                requests_made += 1

                if not isinstance(payload, dict):
                    raise RuntimeError(
                        "Himalayas search returned an "
                        "unexpected response."
                    )

                page_jobs = payload.get(
                    "jobs",
                    [],
                )

                if not isinstance(page_jobs, list):
                    raise RuntimeError(
                        "Himalayas search returned "
                        "invalid jobs data."
                    )

                if total_count is None:
                    total_count = payload.get(
                        "totalCount"
                    )

                for raw_job in page_jobs:
                    if not isinstance(raw_job, dict):
                        continue

                    key = str(
                        raw_job.get("guid")
                        or raw_job.get(
                            "applicationLink"
                        )
                        or ""
                    ).strip()

                    if key:
                        jobs_by_id[key] = raw_job

                query_job_count += len(
                    page_jobs
                )

                if len(page_jobs) < self.page_limit:
                    break

                if (
                    isinstance(total_count, int)
                    and query_job_count
                    >= total_count
                ):
                    break

                if self.request_delay_seconds:
                    time.sleep(
                        self.request_delay_seconds
                    )

            print(
                "HIMALAYAS SEARCH PROGRESS | "
                f"Query: {query_number}/"
                f"{len(queries)} | "
                f"Query jobs: {query_job_count} | "
                f"Unique jobs: {len(jobs_by_id)}"
            )

        return (
            list(jobs_by_id.values()),
            requests_made,
        )

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
        allowed_locations = (
            self.location_restriction_names(
                raw_job
            )
        )
        categories = raw_job.get("categories") or []
        parent_categories = raw_job.get("parentCategories") or []
        seniority = raw_job.get("seniority") or []

        departments = []

        for value in list(categories) + list(parent_categories) + list(seniority):
            if value and value not in departments:
                departments.append(value)

        description = raw_job.get("description") or raw_job.get("excerpt")
        source_candidates = (
            extract_supported_source_records(
                description
            )
        )
        resolved_apply_url = (
            direct_application_url(
                source_candidates
            )
        )

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
            "location_source": "himalayas_api",
            "location_confidence": 1.0,
            "remote_candidate_scope": (
                "selected_locations"
                if allowed_locations
                else "worldwide"
            ),
            "remote_allowed_locations": allowed_locations,
            "remote_allowed_location_type": "countries",
            "employment_type": self.normalize_employment_type(
                raw_job.get("employmentType")
            ),
            "salary": self.format_salary(raw_job),
            "visa_sponsorship": "Unknown",
            # Himalayas requires visible attribution and a link
            # back to the original Himalayas job listing.
            "posting_url": posting_url,
            "apply_url": (
                resolved_apply_url
                or posting_url
            ),
            "job_description": clean_html_text(description),
            "source_candidates": source_candidates,
            "himalayas_company_slug": raw_job.get(
                "companySlug"
            ),
            "departments": departments,
            "offices": [],
            # Himalayas exposes seniority as an array. Keep it in a
            # dedicated structured field so the shared matcher can
            # strictly enforce the profile's selected experience levels.
            "experience_level": seniority,
            "seniority": seniority,
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
            source_class._cache_signature = (
                "recent_feed",
            )

            print(
                "HIMALAYAS FEED | "
                f"Fetched {len(normalized_jobs)} jobs."
            )

            return list(normalized_jobs)

    def prepare(self, profiles):
        queries = self.build_search_queries(
            profiles
        )

        if not queries:
            self._prepared_jobs = []
            self._prepared_stats = {
                "queries": 0,
                "network_requests": 0,
                "jobs": 0,
            }
            return []

        signature = tuple(
            tuple(sorted(query.items()))
            for query in queries
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
                self._prepared_stats = {
                    "queries": len(queries),
                    "network_requests": 0,
                    "jobs": len(
                        self._prepared_jobs
                    ),
                    "cache_hit": True,
                }
                return list(
                    self._prepared_jobs
                )

            raw_jobs, requests_made = (
                self.fetch_search_jobs(
                    queries
                )
            )
            normalized_jobs = [
                self.normalize_job(raw_job)
                for raw_job in raw_jobs
            ]
            normalized_jobs = [
                job
                for job in normalized_jobs
                if job.get("posting_url")
            ]

            source_class._cached_jobs = (
                normalized_jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(timezone.utc)
            )
            source_class._cache_signature = (
                signature
            )

            self._prepared_jobs = list(
                normalized_jobs
            )
            self._prepared_stats = {
                "queries": len(queries),
                "network_requests": requests_made,
                "jobs": len(normalized_jobs),
                "cache_hit": False,
            }

        print(
            "HIMALAYAS PROFILE SCAN COMPLETE | "
            f"Queries: {len(queries)} | "
            f"Requests: {requests_made} | "
            f"Unique jobs: {len(normalized_jobs)}"
        )

        return list(
            normalized_jobs
        )

    def search(self, profile, source_config=None):
        jobs = (
            list(self._prepared_jobs)
            if isinstance(
                self._prepared_jobs,
                list,
            )
            else self.prepare([profile])
        )

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
