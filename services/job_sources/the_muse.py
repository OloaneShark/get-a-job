
import os
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class TheMuseJobSource(BaseJobSource):
    source_name = "The Muse"
    source_type = "the_muse"
    requires_company_config = False

    api_url = "https://www.themuse.com/api/public/jobs"
    tech_categories = (
        "Computer and IT",
        "Data and Analytics",
        "Data Science",
        "Design and UX",
        "Science and Engineering",
        "Software Engineering",
    )
    pages_per_query = 3
    max_locations_per_profile = 3
    max_queries_per_prepare = 60
    cache_duration = timedelta(hours=6)
    stored_description_limit = 1500

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

    @classmethod
    def credentials(cls):
        return str(
            os.getenv(
                "THE_MUSE_API_KEY",
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
    def profile_constraints_supported(
        cls,
        profile,
    ):
        overseas = str(
            getattr(
                profile,
                "overseas_applicant_preference",
                "any",
            )
            or "any"
        ).strip().lower()

        return overseas in {
            "",
            "any",
            "all",
        }

    @classmethod
    def profile_requests_remote(
        cls,
        profile,
    ):
        workplace_types = {
            value.strip().lower()
            for value in cls.parse_profile_values(
                getattr(
                    profile,
                    "workplace_types",
                    None,
                )
            )
        }

        if workplace_types:
            return "remote" in workplace_types

        return bool(
            getattr(
                profile,
                "remote_only",
                False,
            )
        )

    @classmethod
    def build_search_locations(
        cls,
        profile,
    ):
        locations = []
        seen = set()

        for value in cls.parse_profile_values(
            getattr(
                profile,
                "locations",
                None,
            )
        )[:cls.max_locations_per_profile]:
            key = value.lower()

            if key in seen:
                continue

            seen.add(key)
            locations.append(
                {
                    "api_location": value,
                    "scope_location": value,
                }
            )

        if cls.profile_requests_remote(
            profile
        ):
            remote_value = "Flexible / Remote"
            key = remote_value.lower()

            if key not in seen:
                locations.append(
                    {
                        "api_location": remote_value,
                        "scope_location": None,
                    }
                )

        return locations

    @classmethod
    def build_profile_queries(
        cls,
        profile,
    ):
        if not cls.profile_constraints_supported(
            profile
        ):
            return []

        if not cls.parse_profile_values(
            getattr(
                profile,
                "keywords",
                None,
            )
        ):
            return []

        locations = cls.build_search_locations(
            profile
        )

        if not locations:
            return []

        return [
            {
                "category": category,
                "api_location": location[
                    "api_location"
                ],
                "scope_location": location[
                    "scope_location"
                ],
            }
            for location in locations
            for category in cls.tech_categories
        ]

    @classmethod
    def cache_is_fresh(
        cls,
        entry,
    ):
        fetched_at = (
            entry or {}
        ).get(
            "fetched_at"
        )

        return bool(
            fetched_at
            and (
                datetime.now(timezone.utc)
                - fetched_at
                < cls.cache_duration
            )
        )

    @staticmethod
    def list_names(
        values,
    ):
        if not isinstance(
            values,
            list,
        ):
            return []

        names = []
        seen = set()

        for item in values:
            if isinstance(
                item,
                dict,
            ):
                value = item.get(
                    "name"
                )
            else:
                value = item

            value = str(
                value or ""
            ).strip()

            if not value:
                continue

            key = value.lower()

            if key in seen:
                continue

            seen.add(key)
            names.append(value)

        return names

    @staticmethod
    def normalize_level(
        value,
    ):
        normalized = re.sub(
            r"\s+",
            " ",
            str(value or "")
            .strip()
            .lower(),
        )

        mappings = {
            "internship": "intern",
            "entry level": "entry",
            "mid level": "mid",
            "senior level": "senior",
            "management": "manager",
        }

        return mappings.get(
            normalized,
            normalized,
        )

    @classmethod
    def normalize_levels(
        cls,
        values,
    ):
        levels = []

        for value in cls.list_names(
            values
        ):
            normalized = (
                cls.normalize_level(
                    value
                )
            )

            if (
                normalized
                and normalized
                not in levels
            ):
                levels.append(
                    normalized
                )

        return levels

    @staticmethod
    def is_generic_remote_location(
        value,
    ):
        normalized = re.sub(
            r"\s+",
            " ",
            str(value or "")
            .strip()
            .lower(),
        )

        return normalized in {
            "",
            "remote",
            "flexible / remote",
            "remote / flexible",
            "flexible remote",
            "fully remote",
            "work from home",
        }

    @classmethod
    def detect_workplace_type(
        cls,
        locations,
        description,
    ):
        location_text = " | ".join(
            locations
        ).lower()

        if re.search(
            r"\bremote\b|"
            r"\bflexible\s*/\s*remote\b|"
            r"\bremote\s*/\s*flexible\b",
            location_text,
        ):
            return "Remote"

        text = str(
            description or ""
        ).lower()

        if re.search(
            r"\bhybrid\b",
            text,
        ):
            return "Hybrid"

        return None

    @classmethod
    def normalize_job(
        cls,
        raw_job,
        query,
    ):
        if not isinstance(
            raw_job,
            dict,
        ):
            return None

        refs = raw_job.get(
            "refs"
        )
        refs = (
            refs
            if isinstance(
                refs,
                dict,
            )
            else {}
        )

        posting_url = str(
            refs.get(
                "landing_page"
            )
            or ""
        ).strip()

        if not posting_url:
            return None

        title = str(
            raw_job.get("name")
            or "Untitled Position"
        ).strip()

        company = raw_job.get(
            "company"
        )
        company = (
            company
            if isinstance(
                company,
                dict,
            )
            else {}
        )

        company_name = str(
            company.get("name")
            or "Unknown Company"
        ).strip()

        locations = cls.list_names(
            raw_job.get(
                "locations"
            )
        )
        categories = cls.list_names(
            raw_job.get(
                "categories"
            )
        )
        levels = cls.normalize_levels(
            raw_job.get(
                "levels"
            )
        )

        description = clean_html_text(
            raw_job.get(
                "contents"
            )
        )

        workplace_type = (
            cls.detect_workplace_type(
                locations,
                description,
            )
        )

        location = (
            " | ".join(locations)
            if locations
            else None
        )

        scope_location = query.get(
            "scope_location"
        )
        remote_candidate_scope = None
        remote_allowed_locations = []
        location_source = None
        location_confidence = None

        if (
            workplace_type == "Remote"
            and scope_location
            and (
                not locations
                or all(
                    cls.is_generic_remote_location(
                        value
                    )
                    for value in locations
                )
            )
        ):
            remote_candidate_scope = (
                "selected_locations"
            )
            remote_allowed_locations = [
                str(
                    scope_location
                ).strip()
            ]
            location_source = (
                "the_muse_search_scope"
            )
            location_confidence = 0.9

        if (
            not location
            and scope_location
        ):
            location = str(
                scope_location
            ).strip()
            location_source = (
                "the_muse_search_scope"
            )
            location_confidence = 0.9

        employment_type = None

        if (
            "intern"
            in levels
            or re.search(
                r"\b(?:intern|internship)\b",
                title,
                re.IGNORECASE,
            )
        ):
            employment_type = (
                "Internship"
            )

        external_id = str(
            raw_job.get("id")
            or posting_url
        ).strip()

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": company_name,
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
                employment_type
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": (
                description
            ),
            "departments": categories,
            "offices": locations,
            "experience_level": levels,
            "is_remote": (
                workplace_type == "Remote"
            ),
            "workplace_type": (
                workplace_type
            ),
            "published_at": (
                raw_job.get(
                    "publication_date"
                )
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @staticmethod
    def merge_job_context(
        existing,
        incoming,
    ):
        if (
            incoming.get(
                "workplace_type"
            )
            == "Remote"
        ):
            existing[
                "workplace_type"
            ] = "Remote"
            existing[
                "is_remote"
            ] = True

        merged_locations = []

        for location in (
            list(
                existing.get(
                    "remote_allowed_locations"
                )
                or []
            )
            + list(
                incoming.get(
                    "remote_allowed_locations"
                )
                or []
            )
        ):
            location = str(
                location or ""
            ).strip()

            if (
                location
                and location
                not in merged_locations
            ):
                merged_locations.append(
                    location
                )

        if merged_locations:
            existing[
                "remote_candidate_scope"
            ] = "selected_locations"
            existing[
                "remote_allowed_locations"
            ] = merged_locations
            existing[
                "location_source"
            ] = (
                existing.get(
                    "location_source"
                )
                or "the_muse_search_scope"
            )
            existing[
                "location_confidence"
            ] = (
                existing.get(
                    "location_confidence"
                )
                if existing.get(
                    "location_confidence"
                )
                is not None
                else 0.9
            )

        return existing

    @classmethod
    def request_page(
        cls,
        query,
        page,
    ):
        params = {
            "page": page,
            "descending": "true",
            "category": query[
                "category"
            ],
            "location": query[
                "api_location"
            ],
            "api_key": cls.credentials(),
        }

        data = fetch_json(
            cls.api_url,
            params=params,
            timeout=30,
        )

        if not isinstance(
            data,
            dict,
        ):
            raise RuntimeError(
                "The Muse returned an "
                "unexpected response."
            )

        results = data.get(
            "results",
            [],
        )

        if not isinstance(
            results,
            list,
        ):
            raise RuntimeError(
                "The Muse returned invalid "
                "jobs data."
            )

        return (
            results,
            data.get(
                "page_count"
            ),
            data.get(
                "total"
            ),
        )

    @classmethod
    def fetch_query(
        cls,
        query,
    ):
        cache_key = (
            query[
                "category"
            ].lower(),
            query[
                "api_location"
            ].lower(),
        )

        with cls._cache_lock:
            cached = (
                cls._query_cache.get(
                    cache_key
                )
            )

            if cls.cache_is_fresh(
                cached
            ):
                return (
                    list(
                        cached[
                            "jobs"
                        ]
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
            cls.pages_per_query
        ):
            (
                raw_jobs,
                page_count,
                page_total,
            ) = cls.request_page(
                query,
                page,
            )
            network_requests += 1

            if total_count is None:
                total_count = (
                    page_total
                )

            for raw_job in raw_jobs:
                job = cls.normalize_job(
                    raw_job,
                    query,
                )

                if job is not None:
                    normalized_jobs.append(
                        job
                    )

            if not raw_jobs:
                break

            try:
                page_count_value = int(
                    page_count
                )
            except (
                TypeError,
                ValueError,
            ):
                page_count_value = None

            if (
                page_count_value
                is not None
                and page >= (
                    page_count_value - 1
                )
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

            if not key:
                continue

            key = str(key)

            if key in deduplicated:
                deduplicated[
                    key
                ] = cls.merge_job_context(
                    deduplicated[key],
                    job,
                )
            else:
                deduplicated[
                    key
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
                "total_count": (
                    total_count
                ),
            }

        return (
            jobs,
            False,
            network_requests,
            total_count,
        )

    @classmethod
    def collect_prepare_queries(
        cls,
        profiles,
    ):
        per_profile = []
        skipped = 0

        for profile in profiles:
            if not cls.profile_constraints_supported(
                profile
            ):
                skipped += 1
                continue

            queries = cls.build_profile_queries(
                profile
            )

            if queries:
                per_profile.append(
                    queries
                )

        selected = []
        seen = set()
        index = 0

        while (
            len(selected)
            < cls.max_queries_per_prepare
        ):
            added_this_round = False

            for queries in per_profile:
                if index >= len(
                    queries
                ):
                    continue

                query = queries[index]
                key = (
                    query[
                        "category"
                    ].lower(),
                    query[
                        "api_location"
                    ].lower(),
                )

                if key not in seen:
                    seen.add(key)
                    selected.append(
                        query
                    )
                    added_this_round = True

                    if (
                        len(selected)
                        >= cls.max_queries_per_prepare
                    ):
                        break

            if not added_this_round:
                break

            index += 1

        return (
            selected,
            skipped,
        )

    def prepare(
        self,
        profiles,
    ):
        self._prepared = True
        self._prepared_jobs = []
        self._prepared_stats = {
            "queries": 0,
            "network_requests": 0,
            "cached_queries": 0,
            "query_errors": 0,
            "profiles_skipped": 0,
        }

        if not self.credentials_available():
            print(
                "THE MUSE DISABLED | "
                "Set THE_MUSE_API_KEY after "
                "registering the app."
            )
            return []

        (
            queries,
            skipped,
        ) = self.collect_prepare_queries(
            profiles
        )

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
                    "THE MUSE QUERY ERROR | "
                    f"Category: "
                    f"{query['category']} | "
                    f"Location: "
                    f"{query['api_location']} | "
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
                "THE MUSE QUERY | "
                f"Category: "
                f"{query['category']} | "
                f"Location: "
                f"{query['api_location']} | "
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

            if not key:
                continue

            key = str(key)

            if key in deduplicated:
                deduplicated[
                    key
                ] = self.merge_job_context(
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
            "profiles_skipped": (
                skipped
            ),
        }

        print(
            "THE MUSE SHARED FEED | "
            f"Queries: {len(queries)} | "
            f"Network requests: "
            f"{network_requests} | "
            f"Cached queries: "
            f"{cached_queries} | "
            f"Query errors: "
            f"{query_errors} | "
            f"Profiles skipped for "
            f"unsupported overseas "
            f"constraints: {skipped} | "
            f"Unique jobs: "
            f"{len(self._prepared_jobs)}"
        )

        return list(
            self._prepared_jobs
        )

    @classmethod
    def persistable_job(
        cls,
        job,
    ):
        output = dict(job)
        description = output.get(
            "job_description"
        )

        if description:
            description = str(
                description
            ).strip()

            if (
                len(description)
                > cls.stored_description_limit
            ):
                description = (
                    description[
                        :cls.stored_description_limit
                    ].rstrip()
                    + "..."
                )

            output[
                "job_description"
            ] = description or None

        return output

    def search(
        self,
        profile,
        source_config=None,
    ):
        if not self.profile_constraints_supported(
            profile
        ):
            print(
                "THE MUSE SEARCH SKIPPED | "
                f"Profile: {profile.name} | "
                "The Muse does not expose "
                "a reliable overseas-applicant "
                "acceptance signal."
            )
            return []

        if not self.credentials_available():
            return []

        if not self._prepared:
            self.prepare(
                [profile]
            )

        matches = []

        for job in self._prepared_jobs:
            if job_matches_profile(
                job,
                profile,
            ):
                matches.append(
                    self.persistable_job(
                        job
                    )
                )

        print(
            "THE MUSE SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: "
            f"{len(self._prepared_jobs)} | "
            f"Matched: {len(matches)}"
        )

        return matches
