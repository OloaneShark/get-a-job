
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class AmazonJobsSource(BaseJobSource):
    source_name = "Amazon Jobs"
    source_type = "amazon_jobs"
    requires_company_config = False

    feed_url = "https://www.amazon.jobs/en/search.json"
    base_url = "https://www.amazon.jobs"
    page_size = 100
    max_results_per_category = 10000
    max_workers = 4
    cache_duration = timedelta(hours=6)

    tech_categories = (
        (
            "software-development",
            "Software Development",
            {
                "software development",
            },
        ),
        (
            "systems-quality-security-engineering",
            "Systems, Quality, & Security Engineering",
            {
                "systems, quality, & security engineering",
                "systems, quality, and security engineering",
            },
        ),
        (
            "operations-it-support-engineering",
            "Operations, IT, & Support Engineering",
            {
                "operations, it, & support engineering",
                "operations, it, and support engineering",
            },
        ),
        (
            "solutions-architect",
            "Solutions Architect",
            {
                "solutions architect",
                "solution architect",
                "solutions architecture",
            },
        ),
        (
            "business-intelligence",
            "Business Intelligence",
            {
                "business intelligence",
                "business intelligence and data engineering",
            },
        ),
        (
            "data-science",
            "Data Science",
            {
                "data science",
            },
        ),
        (
            "database-administration",
            "Database Administration",
            {
                "database administration",
            },
        ),
        (
            "applied-science",
            "Applied Science",
            {
                "applied science",
                "machine learning science",
            },
        ),
        (
            "research-science",
            "Research Science",
            {
                "research science",
            },
        ),
        (
            "hardware-development",
            "Hardware Development",
            {
                "hardware development",
            },
        ),
    )

    country_names = {
        "ARG": "Argentina",
        "AUS": "Australia",
        "AUT": "Austria",
        "BEL": "Belgium",
        "BHR": "Bahrain",
        "BRA": "Brazil",
        "CAN": "Canada",
        "CHE": "Switzerland",
        "CHL": "Chile",
        "CHN": "China",
        "COL": "Colombia",
        "CRI": "Costa Rica",
        "DEU": "Germany",
        "DNK": "Denmark",
        "EGY": "Egypt",
        "ESP": "Spain",
        "FRA": "France",
        "GBR": "United Kingdom",
        "HKG": "Hong Kong",
        "IDN": "Indonesia",
        "IND": "India",
        "IRL": "Ireland",
        "ISR": "Israel",
        "ITA": "Italy",
        "JPN": "Japan",
        "KOR": "Korea, Republic of",
        "MEX": "Mexico",
        "MYS": "Malaysia",
        "NLD": "Netherlands",
        "NOR": "Norway",
        "NZL": "New Zealand",
        "PHL": "Philippines",
        "POL": "Poland",
        "PRT": "Portugal",
        "ROU": "Romania",
        "SAU": "Saudi Arabia",
        "SGP": "Singapore",
        "SWE": "Sweden",
        "THA": "Thailand",
        "TWN": "Taiwan",
        "USA": "United States",
        "VNM": "Vietnam",
        "ZAF": "South Africa",
    }

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

    @staticmethod
    def normalize_text(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

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

    @classmethod
    def category_params(
        cls,
        category_slug,
        offset,
    ):
        return {
            "base_query": "",
            "offset": int(offset),
            "result_limit": cls.page_size,
            "sort": "recent",
            "category[]": category_slug,
        }

    @classmethod
    def fetch_page(
        cls,
        category_slug,
        offset,
    ):
        payload = fetch_json(
            cls.feed_url,
            params=cls.category_params(
                category_slug,
                offset,
            ),
            timeout=45,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Amazon Jobs returned an unexpected "
                "top-level response."
            )

        jobs = payload.get("jobs")

        if not isinstance(jobs, list):
            raise RuntimeError(
                "Amazon Jobs returned invalid jobs data."
            )

        valid_jobs = [
            job
            for job in jobs
            if isinstance(job, dict)
        ]

        try:
            hits = int(
                payload.get("hits")
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            hits = 0

        return (
            valid_jobs,
            max(0, hits),
        )

    @classmethod
    def category_filter_looks_valid(
        cls,
        jobs,
        accepted_labels,
    ):
        if not jobs:
            return True

        accepted = {
            cls.normalize_text(label)
            .casefold()
            for label in accepted_labels
            if cls.normalize_text(label)
        }

        observed = {
            cls.normalize_text(
                job.get("job_category")
            ).casefold()
            for job in jobs
            if cls.normalize_text(
                job.get("job_category")
            )
        }

        if not observed:
            return True

        return bool(
            observed & accepted
        )

    @classmethod
    def fetch_category(
        cls,
        category_slug,
        category_label,
        accepted_labels,
    ):
        first_page, hits = cls.fetch_page(
            category_slug,
            0,
        )
        requests_used = 1

        if not cls.category_filter_looks_valid(
            first_page,
            accepted_labels,
        ):
            observed = sorted({
                cls.normalize_text(
                    job.get("job_category")
                )
                for job in first_page
                if cls.normalize_text(
                    job.get("job_category")
                )
            })

            raise RuntimeError(
                "Amazon appears to have ignored category "
                f"filter '{category_slug}'. "
                f"Observed categories: {observed[:8]}"
            )

        capped_hits = min(
            hits,
            cls.max_results_per_category,
        )

        if hits > cls.max_results_per_category:
            print(
                "AMAZON JOBS CATEGORY CAP | "
                f"Category: {category_label} | "
                f"Hits: {hits} | "
                f"Cap: {cls.max_results_per_category}"
            )

        jobs = list(
            first_page
        )

        for offset in range(
            cls.page_size,
            capped_hits,
            cls.page_size,
        ):
            page_jobs, _ = cls.fetch_page(
                category_slug,
                offset,
            )
            requests_used += 1

            if not page_jobs:
                break

            jobs.extend(
                page_jobs
            )

            if len(page_jobs) < cls.page_size:
                break

        print(
            "AMAZON JOBS CATEGORY | "
            f"Category: {category_label} | "
            f"Hits: {hits} | "
            f"Fetched: {len(jobs)} | "
            f"Requests: {requests_used}"
        )

        return {
            "slug": category_slug,
            "label": category_label,
            "hits": hits,
            "jobs": jobs,
            "requests": requests_used,
        }

    @classmethod
    def country_name(
        cls,
        value,
    ):
        text = cls.normalize_text(
            value
        )

        if not text:
            return None

        return cls.country_names.get(
            text.upper(),
            text,
        )

    @classmethod
    def format_location_dict(
        cls,
        value,
    ):
        if not isinstance(
            value,
            dict,
        ):
            return None

        city = cls.normalize_text(
            value.get("city")
            or value.get("locality")
        )
        state = cls.normalize_text(
            value.get("state")
            or value.get("region")
            or value.get("state_code")
        )
        country = cls.country_name(
            value.get("country_code")
            or value.get("country")
        )

        parts = []

        for item in (
            city,
            state,
            country,
        ):
            if (
                item
                and item.casefold()
                not in {
                    existing.casefold()
                    for existing
                    in parts
                }
            ):
                parts.append(item)

        if not parts:
            return None

        return ", ".join(parts)

    @classmethod
    def collect_locations(
        cls,
        raw_job,
    ):
        locations = []

        def add(value):
            text = cls.normalize_text(
                value
            )

            if not text:
                return

            key = text.casefold()

            if key in {
                existing.casefold()
                for existing in locations
            }:
                return

            locations.append(text)

        structured_primary = (
            cls.format_location_dict({
                "city": raw_job.get("city"),
                "state": raw_job.get("state"),
                "country_code": raw_job.get(
                    "country_code"
                ),
            })
        )

        if structured_primary:
            add(
                structured_primary
            )

        nested = (
            raw_job.get("locations")
            or []
        )

        if isinstance(
            nested,
            (list, tuple),
        ):
            for item in nested:
                if isinstance(
                    item,
                    dict,
                ):
                    add(
                        cls.format_location_dict(
                            item
                        )
                        or item.get("name")
                        or item.get("label")
                        or item.get("location")
                    )
                else:
                    add(item)

        if not locations:
            add(
                raw_job.get("location")
            )

        if not locations:
            normalized_location = (
                raw_job.get(
                    "normalized_location"
                )
            )

            if isinstance(
                normalized_location,
                dict,
            ):
                add(
                    cls.format_location_dict(
                        normalized_location
                    )
                )
            else:
                add(
                    normalized_location
                )

        return locations

    @classmethod
    def combined_description(
        cls,
        raw_job,
    ):
        sections = []

        description = clean_html_text(
            raw_job.get("description")
        )

        if description:
            sections.append(
                description
            )

        basic = clean_html_text(
            raw_job.get(
                "basic_qualifications"
            )
        )

        if basic:
            sections.append(
                "Basic qualifications:\n"
                f"{basic}"
            )

        preferred = clean_html_text(
            raw_job.get(
                "preferred_qualifications"
            )
        )

        if preferred:
            sections.append(
                "Preferred qualifications:\n"
                f"{preferred}"
            )

        return (
            "\n\n".join(
                sections
            ).strip()
            or None
        )

    @classmethod
    def detect_workplace_type(
        cls,
        title,
        locations,
        description,
    ):
        location_text = cls.normalize_text(
            " | ".join(
                locations
            )
        ).casefold()

        searchable = cls.normalize_text(
            " ".join([
                title or "",
                description or "",
            ])
        ).casefold()

        negative_remote_patterns = (
            r"\bnot offered remote or hybrid\b",
            r"\bnot (?:a )?remote (?:role|position)\b",
            r"\bnot eligible for remote work\b",
            r"\bon[- ]site only\b",
            r"\bin[- ]office only\b",
        )

        if any(
            re.search(
                pattern,
                searchable,
            )
            for pattern
            in negative_remote_patterns
        ):
            return "On-site"

        hybrid_patterns = (
            r"\bhybrid (?:role|position|schedule|work)\b",
            r"\bhybrid work model\b",
            r"\bwork(?:ing)? in a hybrid\b",
        )

        if any(
            re.search(
                pattern,
                searchable,
            )
            for pattern
            in hybrid_patterns
        ):
            return "Hybrid"

        remote_location_terms = (
            "virtual location",
            "virtual,",
            "remote",
            "work from home",
            "home-based",
            "home based",
        )

        if any(
            term in location_text
            for term
            in remote_location_terms
        ):
            return "Remote"

        remote_description_patterns = (
            r"\bthis is (?:a )?remote (?:role|position)\b",
            r"\bfully remote\b",
            r"\bremote-first\b",
            r"\bwork from home\b",
            r"\bvirtual position\b",
        )

        if any(
            re.search(
                pattern,
                searchable,
            )
            for pattern
            in remote_description_patterns
        ):
            return "Remote"

        return "On-site"

    @classmethod
    def remote_locations_are_specific(
        cls,
        locations,
    ):
        generic = {
            "remote",
            "virtual",
            "virtual location",
            "virtual locations",
            "remote location",
            "remote locations",
            "worldwide",
            "global",
        }

        for location in locations:
            normalized = cls.normalize_text(
                location
            ).casefold()

            if not normalized:
                continue

            if normalized not in generic:
                return True

        return False

    @classmethod
    def normalize_employment_type(
        cls,
        raw_job,
        title,
    ):
        title_text = cls.normalize_text(
            title
        ).casefold()

        if (
            raw_job.get("is_intern")
            or "intern" in title_text
        ):
            return "Internship"

        value = cls.normalize_text(
            raw_job.get(
                "job_schedule_type"
            )
        ).casefold()

        mapping = {
            "full time": "Full-time",
            "full-time": "Full-time",
            "fulltime": "Full-time",
            "part time": "Part-time",
            "part-time": "Part-time",
            "parttime": "Part-time",
            "temporary": "Temporary",
            "seasonal": "Temporary",
            "contract": "Contract",
        }

        return mapping.get(
            value
        )

    @classmethod
    def normalize_experience_level(
        cls,
        raw_job,
        title,
    ):
        title_text = cls.normalize_text(
            title
        ).casefold()

        if (
            raw_job.get("is_intern")
            or "intern" in title_text
        ):
            return "intern"

        if (
            "early career" in title_text
            or "new grad" in title_text
            or "new graduate" in title_text
            or raw_job.get(
                "university_job"
            )
        ):
            return "entry"

        if re.search(
            r"\bjunior\b|\bjr\.?\b",
            title_text,
        ):
            return "junior"

        if raw_job.get(
            "is_manager"
        ):
            return "manager"

        return None

    @classmethod
    def parse_posted_date(
        cls,
        value,
    ):
        text = cls.normalize_text(
            value
        )

        if not text:
            return None

        for format_string in (
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(
                    text,
                    format_string,
                )
            except ValueError:
                continue

            return parsed.replace(
                tzinfo=timezone.utc
            )

        return value

    @classmethod
    def normalize_url(
        cls,
        value,
        fallback=None,
    ):
        text = cls.normalize_text(
            value
        )

        if not text:
            return fallback

        return urljoin(
            cls.base_url,
            text,
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
            raw_job.get("id_icims")
            or raw_job.get("id")
        )
        title = cls.normalize_text(
            raw_job.get("title")
        )
        job_path = cls.normalize_text(
            raw_job.get("job_path")
        )
        posting_url = cls.normalize_url(
            job_path
        )

        if (
            not external_id
            or not title
            or not posting_url
        ):
            return None

        company_name = cls.normalize_text(
            raw_job.get("company_name")
        ) or "Amazon"

        locations = cls.collect_locations(
            raw_job
        )
        description = (
            cls.combined_description(
                raw_job
            )
        )

        workplace_type = (
            cls.detect_workplace_type(
                title,
                locations,
                description,
            )
        )

        if workplace_type == "Remote":
            if (
                locations
                and cls.remote_locations_are_specific(
                    locations
                )
            ):
                location = (
                    "Remote | "
                    + " | ".join(
                        locations
                    )
                )
                location_source = (
                    "amazon_jobs_api_remote_location"
                )
                location_confidence = 0.9
                remote_candidate_scope = (
                    "selected_locations"
                )
                remote_allowed_locations = (
                    list(locations)
                )
            else:
                location = "Remote"
                location_source = (
                    "amazon_jobs_api_remote_unspecified"
                )
                location_confidence = 0.4
                remote_candidate_scope = None
                remote_allowed_locations = []
        else:
            location = (
                " | ".join(
                    locations
                )
                if locations
                else "Unknown"
            )
            location_source = (
                "amazon_jobs_api"
                if locations
                else "unknown"
            )
            location_confidence = (
                1.0
                if locations
                else 0.0
            )
            remote_candidate_scope = None
            remote_allowed_locations = []

        experience_level = (
            cls.normalize_experience_level(
                raw_job,
                title,
            )
        )

        apply_url = cls.normalize_url(
            raw_job.get(
                "url_next_step"
            ),
            fallback=posting_url,
        )

        tags = []

        for value in (
            raw_job.get(
                "job_category"
            ),
            raw_job.get(
                "job_family"
            ),
            raw_job.get(
                "business_category"
            ),
            raw_job.get(
                "primary_search_label"
            ),
        ):
            text = cls.normalize_text(
                value
            )

            if (
                text
                and text.casefold()
                not in {
                    existing.casefold()
                    for existing
                    in tags
                }
            ):
                tags.append(text)

        team = raw_job.get("team")

        if isinstance(
            team,
            dict,
        ):
            team_label = cls.normalize_text(
                team.get("title")
                or team.get("label")
            )

            if (
                team_label
                and team_label.casefold()
                not in {
                    existing.casefold()
                    for existing
                    in tags
                }
            ):
                tags.append(
                    team_label
                )

        category = cls.normalize_text(
            raw_job.get(
                "job_category"
            )
        )
        family = cls.normalize_text(
            raw_job.get(
                "job_family"
            )
        )

        departments = []

        for value in (
            category,
            family,
        ):
            if (
                value
                and value.casefold()
                not in {
                    existing.casefold()
                    for existing
                    in departments
                }
            ):
                departments.append(
                    value
                )

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
            "employment_type": (
                cls.normalize_employment_type(
                    raw_job,
                    title,
                )
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": description,
            "is_remote": (
                workplace_type
                in {
                    "Remote",
                    "Hybrid",
                }
            ),
            "workplace_type": (
                workplace_type
            ),
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "published_at": (
                cls.parse_posted_date(
                    raw_job.get(
                        "posted_date"
                    )
                )
            ),
            "experience_level": (
                experience_level
            ),
            "seniority_level": (
                experience_level
            ),
            "tags": tags,
            "departments": departments,
            "offices": list(
                locations
            ),
            "source_listing_url": (
                cls.base_url
                + "/en/search"
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def prepare_jobs(
        cls,
    ):
        category_results = []
        category_errors = {}

        with ThreadPoolExecutor(
            max_workers=cls.max_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.fetch_category,
                    slug,
                    label,
                    accepted_labels,
                ): (
                    slug,
                    label,
                )
                for (
                    slug,
                    label,
                    accepted_labels,
                )
                in cls.tech_categories
            }

            for future in as_completed(
                future_map
            ):
                slug, label = (
                    future_map[future]
                )

                try:
                    result = (
                        future.result()
                    )
                except Exception as error:
                    category_errors[
                        slug
                    ] = str(error)

                    print(
                        "AMAZON JOBS CATEGORY FAILED | "
                        f"Category: {label} | "
                        f"Error: {error}"
                    )
                    continue

                category_results.append(
                    result
                )

        if (
            not category_results
            and category_errors
        ):
            raise RuntimeError(
                "Amazon Jobs failed for every "
                "technology category."
            )

        raw_jobs = []

        for result in category_results:
            raw_jobs.extend(
                result["jobs"]
            )

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
            key = cls.normalize_text(
                job.get(
                    "external_id"
                )
                or job.get(
                    "posting_url"
                )
            )

            if not key:
                invalid += 1
                continue

            deduplicated[key] = job

        prepared_jobs = list(
            deduplicated.values()
        )

        requests_used = sum(
            int(
                result.get(
                    "requests"
                )
                or 0
            )
            for result
            in category_results
        )

        stats = {
            "categories_attempted": len(
                cls.tech_categories
            ),
            "categories_succeeded": len(
                category_results
            ),
            "categories_failed": len(
                category_errors
            ),
            "raw": len(raw_jobs),
            "normalized": len(
                normalized_jobs
            ),
            "invalid": invalid,
            "unique": len(
                prepared_jobs
            ),
            "requests": requests_used,
            "category_errors": (
                category_errors
            ),
            "category_counts": {
                result["slug"]: {
                    "hits": result[
                        "hits"
                    ],
                    "fetched": len(
                        result["jobs"]
                    ),
                    "requests": result[
                        "requests"
                    ],
                }
                for result
                in category_results
            },
        }

        print(
            "AMAZON JOBS FEED | "
            f"Categories: "
            f"{stats['categories_succeeded']}/"
            f"{stats['categories_attempted']} | "
            f"Raw: {stats['raw']} | "
            f"Normalized: "
            f"{stats['normalized']} | "
            f"Invalid: {stats['invalid']} | "
            f"Unique: {stats['unique']} | "
            f"Requests: {stats['requests']} | "
            f"Category errors: "
            f"{stats['categories_failed']}"
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
            if (
                source_class.cache_is_fresh()
            ):
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "AMAZON JOBS CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        jobs, stats = (
            source_class.prepare_jobs()
        )

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
            "AMAZON JOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: "
            f"{len(self._prepared_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
