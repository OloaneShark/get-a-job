import os
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class USAJobsJobSource(BaseJobSource):
    source_name = "USAJOBS"
    source_type = "usajobs"
    requires_company_config = False

    api_url = "https://data.usajobs.gov/api/search"
    federal_tech_series = (
        "0332",
        "0335",
        "0391",
        "0854",
        "0855",
        "0856",
        "1550",
        "1560",
        "2210",
    )
    results_per_page = 500
    max_terms_per_profile = 10
    max_locations_per_profile = 3
    max_queries_per_prepare = 30
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
            for item in re.split(r"[\n,]+", str(value))
            if item.strip()
        ]

    @staticmethod
    def normalize_keyword(value):
        text = str(value or "").strip().lower()
        text = text.replace("full-stack", "full stack")
        text = text.replace("fullstack", "full stack")
        return re.sub(r"\s+", " ", text)

    @classmethod
    def build_search_terms(cls, profile):
        values = cls.parse_profile_values(
            getattr(profile, "keywords", None)
        )
        terms = []
        seen = set()

        for value in values:
            normalized = cls.normalize_keyword(value)

            if not normalized or normalized in seen:
                continue

            seen.add(normalized)
            terms.append(normalized)

        return terms[:cls.max_terms_per_profile]

    @classmethod
    def profile_constraints_supported(cls, profile):
        visa = str(
            getattr(profile, "visa_preference", "any")
            or "any"
        ).strip().lower()
        overseas = str(
            getattr(
                profile,
                "overseas_applicant_preference",
                "any",
            )
            or "any"
        ).strip().lower()

        return (
            visa in {"", "any", "all"}
            and overseas in {"", "any", "all"}
        )

    @classmethod
    def profile_remote_only(cls, profile):
        workplace_types = {
            value.strip().lower()
            for value in cls.parse_profile_values(
                getattr(profile, "workplace_types", None)
            )
        }

        if workplace_types:
            return workplace_types == {"remote"}

        return bool(getattr(profile, "remote_only", False))

    @staticmethod
    def is_broad_us_location(value):
        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            str(value or "").strip().lower(),
        ).strip()

        return normalized in {
            "united states",
            "united states of america",
            "usa",
            "us",
        }

    @classmethod
    def build_profile_queries(cls, profile):
        if not cls.profile_constraints_supported(
            profile
        ):
            return []

        terms = cls.build_search_terms(
            profile
        )

        if not terms:
            return []

        locations = cls.parse_profile_values(
            getattr(
                profile,
                "locations",
                None,
            )
        )[:cls.max_locations_per_profile]

        if not locations:
            return []

        remote_only = cls.profile_remote_only(
            profile
        )
        queries = []

        for location in locations:
            queries.append(
                {
                    "query_type": "job_category",
                    "query_value": ";".join(
                        cls.federal_tech_series
                    ),
                    "keyword": None,
                    "location": location,
                    "location_filter": (
                        None
                        if cls.is_broad_us_location(
                            location
                        )
                        else location
                    ),
                    "remote_only": remote_only,
                }
            )

        return queries

    @classmethod
    def query_label(cls, query):
        if query.get("query_type") == "job_category":
            return "tech series " + query["query_value"]

        return str(
            query.get("keyword")
            or query.get("query_value")
            or "unknown"
        )

    @classmethod
    def credentials(cls):
        api_key = str(
            os.getenv("USAJOBS_API_KEY", "") or ""
        ).strip()
        email = str(
            os.getenv("USAJOBS_API_EMAIL", "") or ""
        ).strip()
        return api_key, email

    @classmethod
    def credentials_available(cls):
        api_key, email = cls.credentials()
        return bool(api_key and email)

    @classmethod
    def cache_is_fresh(cls, entry):
        fetched_at = (entry or {}).get("fetched_at")

        return bool(
            fetched_at
            and (
                datetime.now(timezone.utc) - fetched_at
                < cls.cache_duration
            )
        )

    @staticmethod
    def first_name(items):
        if not isinstance(items, list):
            return None

        for item in items:
            if not isinstance(item, dict):
                continue

            value = str(item.get("Name") or "").strip()

            if value:
                return value

        return None

    @staticmethod
    def list_names(items):
        if not isinstance(items, list):
            return []

        names = []
        seen = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            value = str(
                item.get("Name")
                or item.get("LocationName")
                or ""
            ).strip()

            if value and value.lower() not in seen:
                seen.add(value.lower())
                names.append(value)

        return names

    @classmethod
    def normalize_location(cls, descriptor):
        names = cls.list_names(
            descriptor.get("PositionLocation")
        )

        if names:
            return " | ".join(names)

        return str(
            descriptor.get("PositionLocationDisplay")
            or ""
        ).strip() or None

    @classmethod
    def clean_content_value(cls, value):
        if value is None:
            return None

        if isinstance(
            value,
            (list, tuple, set),
        ):
            parts = []

            for item in value:
                cleaned = cls.clean_content_value(
                    item
                )

                if cleaned and cleaned not in parts:
                    parts.append(cleaned)

            return "\n".join(parts) or None

        if isinstance(value, dict):
            preferred_keys = (
                "Requirement",
                "Name",
                "Value",
                "Description",
                "Text",
            )
            parts = []

            for key in preferred_keys:
                if key not in value:
                    continue

                cleaned = cls.clean_content_value(
                    value.get(key)
                )

                if cleaned and cleaned not in parts:
                    parts.append(cleaned)

            if not parts:
                for item in value.values():
                    cleaned = cls.clean_content_value(
                        item
                    )

                    if (
                        cleaned
                        and cleaned not in parts
                    ):
                        parts.append(cleaned)

            return "\n".join(parts) or None

        return clean_html_text(
            str(value)
        )

    @staticmethod
    def normalize_salary(descriptor):
        values = descriptor.get("PositionRemuneration")

        if not isinstance(values, list):
            return None

        for item in values:
            if not isinstance(item, dict):
                continue

            minimum = str(
                item.get("MinimumRange") or ""
            ).strip()
            maximum = str(
                item.get("MaximumRange") or ""
            ).strip()
            description = str(
                item.get("Description")
                or item.get("RateIntervalCode")
                or ""
            ).strip()

            parts = []

            if minimum and maximum:
                parts.append(
                    minimum
                    if minimum == maximum
                    else f"{minimum} - {maximum}"
                )
            elif minimum:
                parts.append(minimum)
            elif maximum:
                parts.append(maximum)

            if description:
                parts.append(description)

            if parts:
                return " ".join(parts)

        return None

    @classmethod
    def normalize_description(cls, descriptor):
        values = []

        qualification = cls.clean_content_value(
            descriptor.get(
                "QualificationSummary"
            )
        )

        if qualification:
            values.append(qualification)

        user_area = descriptor.get("UserArea")
        user_area = (
            user_area
            if isinstance(user_area, dict)
            else {}
        )
        details = user_area.get("Details")
        details = (
            details
            if isinstance(details, dict)
            else {}
        )

        for field_name in (
            "JobSummary",
            "MajorDuties",
            "Requirements",
            "Education",
            "Evaluations",
            "OtherInformation",
            "KeyRequirements",
        ):
            value = cls.clean_content_value(
                details.get(field_name)
            )

            if value and value not in values:
                values.append(value)

        return "\n\n".join(values) or None

    @staticmethod
    def detect_remote(
        title,
        location,
        description,
        query_remote_only,
    ):
        if query_remote_only:
            return True

        text = " ".join(
            [
                str(title or ""),
                str(location or ""),
                str(description or ""),
            ]
        ).lower()

        return bool(
            re.search(
                r"\bremote job\b|"
                r"\bfully remote\b|"
                r"\b100% remote\b|"
                r"\bremote position\b|"
                r"\bremote role\b",
                text,
            )
        )

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
            "remote job",
            "remote position",
            "remote role",
            "fully remote",
        }

    @classmethod
    def normalize_job(cls, raw_item, query):
        if not isinstance(raw_item, dict):
            return None

        descriptor = raw_item.get(
            "MatchedObjectDescriptor"
        )

        if not isinstance(descriptor, dict):
            return None

        category_codes = {
            str(
                item.get("Code")
                or ""
            ).strip()
            for item in (
                descriptor.get(
                    "JobCategory"
                )
                or []
            )
            if isinstance(
                item,
                dict,
            )
        }

        if not category_codes.intersection(
            cls.federal_tech_series
        ):
            return None

        posting_url = str(
            descriptor.get("PositionURI") or ""
        ).strip()

        if not posting_url:
            return None

        apply_url = None
        apply_values = descriptor.get("ApplyURI")

        if isinstance(apply_values, list):
            for value in apply_values:
                value = str(value or "").strip()

                if value:
                    apply_url = value
                    break

        apply_url = apply_url or posting_url

        title = str(
            descriptor.get("PositionTitle")
            or "Untitled Position"
        ).strip()
        location = cls.normalize_location(descriptor)
        description = cls.normalize_description(
            descriptor
        )
        is_remote = cls.detect_remote(
            title,
            location,
            description,
            query.get("remote_only", False),
        )

        remote_candidate_scope = None
        remote_allowed_locations = []
        location_source = None
        location_confidence = None

        if (
            is_remote
            and query.get("location")
            and cls.is_generic_remote_location(location)
        ):
            remote_candidate_scope = "selected_locations"
            remote_allowed_locations = [
                str(query["location"]).strip()
            ]
            location_source = "usajobs_search_scope"
            location_confidence = 0.9

        external_id = str(
            raw_item.get("MatchedObjectId")
            or descriptor.get("PositionID")
            or posting_url
        ).strip()

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": str(
                descriptor.get("OrganizationName")
                or descriptor.get("DepartmentName")
                or "United States Government"
            ).strip(),
            "position_title": title,
            "location": location,
            "location_source": location_source,
            "location_confidence": location_confidence,
            "remote_candidate_scope": remote_candidate_scope,
            "remote_allowed_locations": remote_allowed_locations,
            "employment_type": cls.first_name(
                descriptor.get("PositionSchedule")
            ),
            "salary": cls.normalize_salary(descriptor),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": description,
            "departments": cls.list_names(
                descriptor.get("JobCategory")
            ),
            "offices": cls.list_names(
                descriptor.get("PositionLocation")
            ),
            "is_remote": is_remote,
            "workplace_type": (
                "Remote" if is_remote else None
            ),
            "published_at": (
                descriptor.get("PublicationStartDate")
                or descriptor.get("PositionStartDate")
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @staticmethod
    def merge_job_context(existing, incoming):
        if incoming.get("workplace_type") == "Remote":
            existing["workplace_type"] = "Remote"
            existing["is_remote"] = True

        merged_locations = []

        for location in (
            list(
                existing.get("remote_allowed_locations")
                or []
            )
            + list(
                incoming.get("remote_allowed_locations")
                or []
            )
        ):
            location = str(location or "").strip()

            if (
                location
                and location not in merged_locations
            ):
                merged_locations.append(location)

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
                existing.get("location_source")
                or "usajobs_search_scope"
            )
            existing[
                "location_confidence"
            ] = (
                existing.get("location_confidence")
                if existing.get("location_confidence")
                is not None
                else 0.9
            )

        return existing

    @classmethod
    def request_query(cls, query):
        api_key, email = cls.credentials()

        params = {
            "DatePosted": 60,
            "Fields": "Full",
            "ResultsPerPage": cls.results_per_page,
            "Page": 1,
            "SortField": "opendate",
            "SortDirection": "desc",
        }

        if query.get("query_type") == "job_category":
            params["JobCategoryCode"] = query["query_value"]
        elif query.get("query_type") == "position_title":
            params["PositionTitle"] = query["query_value"]
        elif query.get("keyword"):
            params["Keyword"] = query["keyword"]

        if query.get("location_filter"):
            params["LocationName"] = (
                query["location_filter"]
            )

        if query.get("remote_only"):
            params["RemoteIndicator"] = "True"

        data = fetch_json(
            cls.api_url,
            params=params,
            headers={
                "Host": "data.usajobs.gov",
                "User-Agent": email,
                "Authorization-Key": api_key,
                "Accept": "application/json",
            },
            timeout=30,
        )

        if not isinstance(data, dict):
            raise RuntimeError(
                "USAJOBS returned an unexpected response."
            )

        search_result = data.get("SearchResult")

        if not isinstance(search_result, dict):
            raise RuntimeError(
                "USAJOBS response did not contain SearchResult."
            )

        items = search_result.get(
            "SearchResultItems",
            [],
        )

        if not isinstance(items, list):
            raise RuntimeError(
                "USAJOBS returned invalid SearchResultItems."
            )

        return (
            items,
            search_result.get("SearchResultCountAll"),
        )

    @classmethod
    def fetch_query(cls, query):
        cache_key = (
            str(query.get("query_type") or "keyword").lower(),
            str(
                query.get("query_value")
                or query.get("keyword")
                or ""
            ).lower(),
            query["location"].lower(),
            bool(query.get("remote_only")),
        )

        with cls._cache_lock:
            cached = cls._query_cache.get(cache_key)

            if cls.cache_is_fresh(cached):
                return (
                    list(cached["jobs"]),
                    True,
                    0,
                    cached.get("total_count"),
                )

        raw_items, total_count = cls.request_query(
            query
        )

        deduplicated = {}

        for raw_item in raw_items:
            job = cls.normalize_job(
                raw_item,
                query,
            )

            if job is None:
                continue

            key = (
                job.get("external_id")
                or job.get("posting_url")
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
                deduplicated[key] = job

        jobs = list(deduplicated.values())

        with cls._cache_lock:
            cls._query_cache[cache_key] = {
                "fetched_at": datetime.now(
                    timezone.utc
                ),
                "jobs": list(jobs),
                "total_count": total_count,
            }

        return jobs, False, 1, total_count

    @classmethod
    def collect_prepare_queries(cls, profiles):
        groups = []
        skipped_constraints = 0

        for profile in profiles:
            if not cls.profile_constraints_supported(
                profile
            ):
                skipped_constraints += 1
                groups.append([])
            else:
                groups.append(
                    cls.build_profile_queries(profile)
                )

        selected = []
        seen = set()
        positions = [0 for _ in groups]

        while len(selected) < cls.max_queries_per_prepare:
            added_this_round = False

            for index, group in enumerate(groups):
                while positions[index] < len(group):
                    query = group[positions[index]]
                    positions[index] += 1

                    key = (
                        str(
                            query.get("query_type")
                            or "keyword"
                        ).lower(),
                        str(
                            query.get("query_value")
                            or query.get("keyword")
                            or ""
                        ).lower(),
                        query["location"].lower(),
                        bool(query.get("remote_only")),
                    )

                    if key in seen:
                        continue

                    seen.add(key)
                    selected.append(query)
                    added_this_round = True
                    break

                if (
                    len(selected)
                    >= cls.max_queries_per_prepare
                ):
                    break

            if not added_this_round:
                break

        return selected, skipped_constraints

    def prepare(self, profiles):
        self._prepared = True
        self._prepared_jobs = []

        if not self.credentials_available():
            print(
                "USAJOBS DISABLED | "
                "Set USAJOBS_API_KEY and "
                "USAJOBS_API_EMAIL to enable the source."
            )
            return []

        (
            queries,
            skipped_constraints,
        ) = self.collect_prepare_queries(profiles)

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
                ) = self.fetch_query(query)
            except Exception as error:
                query_errors += 1
                print(
                    "USAJOBS QUERY ERROR | "
                    f"Query: {self.query_label(query)} | "
                    f"Location: {query['location']} | "
                    f"Remote only: {query['remote_only']} | "
                    f"Error: {error}"
                )
                continue

            network_requests += requests_made

            if from_cache:
                cached_queries += 1

            all_jobs.extend(jobs)

            print(
                "USAJOBS QUERY | "
                f"Query: {self.query_label(query)} | "
                f"Location: {query['location']} | "
                f"Remote only: {query['remote_only']} | "
                f"Jobs: {len(jobs)} | "
                f"Reported total: "
                f"{total_count if total_count is not None else 'unknown'} | "
                f"Cache: {'yes' if from_cache else 'no'}"
            )

        deduplicated = {}

        for job in all_jobs:
            key = (
                job.get("external_id")
                or job.get("posting_url")
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
                deduplicated[key] = job

        self._prepared_jobs = list(
            deduplicated.values()
        )

        print(
            "USAJOBS SHARED FEED | "
            f"Queries: {len(queries)} | "
            f"Network requests: {network_requests} | "
            f"Cached queries: {cached_queries} | "
            f"Query errors: {query_errors} | "
            "Profiles skipped for unsupported "
            f"visa/overseas constraints: "
            f"{skipped_constraints} | "
            f"Unique jobs: {len(self._prepared_jobs)}"
        )

        return list(self._prepared_jobs)

    def search(
        self,
        profile,
        source_config=None,
    ):
        if not self.profile_constraints_supported(
            profile
        ):
            print(
                "USAJOBS SEARCH SKIPPED | "
                f"Profile: {profile.name} | "
                "USAJOBS does not expose the required "
                "visa/overseas signal."
            )
            return []

        if not self._prepared:
            self.prepare([profile])

        matching_jobs = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(job, profile)
        ]

        print(
            "USAJOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: {len(self._prepared_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
