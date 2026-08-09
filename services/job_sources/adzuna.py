
import os
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class AdzunaJobSource(BaseJobSource):
    source_name = "Adzuna"
    source_type = "adzuna"
    requires_company_config = False

    api_root = "https://api.adzuna.com/v1/api/jobs"
    category = "it-jobs"
    results_per_page = 50
    pages_per_query = 2
    max_queries_per_prepare = 10
    cache_duration = timedelta(hours=6)

    supported_countries = {
        "australia": "au",
        "austria": "at",
        "belgium": "be",
        "brazil": "br",
        "canada": "ca",
        "france": "fr",
        "germany": "de",
        "india": "in",
        "italy": "it",
        "mexico": "mx",
        "netherlands": "nl",
        "new zealand": "nz",
        "poland": "pl",
        "singapore": "sg",
        "south africa": "za",
        "spain": "es",
        "switzerland": "ch",
        "united kingdom": "gb",
        "uk": "gb",
        "great britain": "gb",
        "united states": "us",
        "united states of america": "us",
        "usa": "us",
        "u.s.": "us",
        "u.s.a.": "us",
    }

    country_names = {
        "au": "Australia",
        "at": "Austria",
        "be": "Belgium",
        "br": "Brazil",
        "ca": "Canada",
        "fr": "France",
        "de": "Germany",
        "in": "India",
        "it": "Italy",
        "mx": "Mexico",
        "nl": "Netherlands",
        "nz": "New Zealand",
        "pl": "Poland",
        "sg": "Singapore",
        "za": "South Africa",
        "es": "Spain",
        "ch": "Switzerland",
        "gb": "United Kingdom",
        "us": "United States",
    }

    currency_codes = {
        "au": "AUD",
        "at": "EUR",
        "be": "EUR",
        "br": "BRL",
        "ca": "CAD",
        "fr": "EUR",
        "de": "EUR",
        "in": "INR",
        "it": "EUR",
        "mx": "MXN",
        "nl": "EUR",
        "nz": "NZD",
        "pl": "PLN",
        "sg": "SGD",
        "za": "ZAR",
        "es": "EUR",
        "ch": "CHF",
        "gb": "GBP",
        "us": "USD",
    }

    search_stopwords = {
        "and",
        "application",
        "associate",
        "developer",
        "development",
        "engineer",
        "engineering",
        "entry",
        "intern",
        "internship",
        "junior",
        "lead",
        "manager",
        "mid",
        "principal",
        "senior",
        "specialist",
        "staff",
        "technical",
        "technician",
        "technology",
    }

    _cache_lock = threading.Lock()
    _query_cache = {}

    def __init__(self):
        self._prepared_jobs = []
        self._prepared = False
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

    @classmethod
    def cache_is_fresh(cls, entry):
        if not entry:
            return False

        fetched_at = entry.get("fetched_at")

        if fetched_at is None:
            return False

        return (
            datetime.now(timezone.utc) - fetched_at
        ) < cls.cache_duration

    @staticmethod
    def credentials():
        return (
            str(os.getenv("ADZUNA_APP_ID", "")).strip(),
            str(os.getenv("ADZUNA_APP_KEY", "")).strip(),
        )

    @classmethod
    def credentials_available(cls):
        app_id, app_key = cls.credentials()
        return bool(app_id and app_key)

    @classmethod
    def resolve_country(cls, location):
        normalized = re.sub(
            r"\s+",
            " ",
            str(location or "").strip().lower(),
        )

        if not normalized:
            return None

        if normalized in cls.supported_countries:
            return cls.supported_countries[normalized]

        for name, code in cls.supported_countries.items():
            if re.search(
                rf"(^|[^a-z]){re.escape(name)}([^a-z]|$)",
                normalized,
            ):
                return code

        return None

    @classmethod
    def build_location_queries(cls, profile):
        queries = []
        seen = set()

        for location in cls.parse_profile_values(
            getattr(profile, "locations", None)
        ):
            country = cls.resolve_country(location)

            if not country:
                continue

            country_name = cls.country_names[country]
            normalized_location = location.strip().lower()
            where = None

            if normalized_location not in {
                country_name.lower(),
                "uk",
                "great britain",
                "usa",
                "u.s.",
                "u.s.a.",
                "united states of america",
            }:
                where = location

            key = (country, str(where or "").lower())

            if key in seen:
                continue

            seen.add(key)
            queries.append({"country": country, "where": where})

        return queries

    @classmethod
    def build_search_terms(cls, profile):
        tokens = []
        seen = set()

        for keyword in cls.parse_profile_values(
            getattr(profile, "keywords", None)
        ):
            normalized = (
                keyword.lower()
                .replace("full-stack", "full stack")
                .replace("fullstack", "full stack")
                .replace("dev sec ops", "devsecops")
            )

            if "full stack" in normalized:
                normalized = normalized.replace("full stack", "stack")

            for token in re.findall(r"[a-z0-9+#.]+", normalized):
                cleaned = token.strip(".")

                if (
                    len(cleaned) < 2
                    or cleaned in cls.search_stopwords
                    or cleaned in seen
                ):
                    continue

                seen.add(cleaned)
                tokens.append(cleaned)

        if not tokens:
            return None

        return " ".join(tokens[:12])

    @classmethod
    def build_profile_queries(cls, profile):
        what_or = cls.build_search_terms(profile)

        if not what_or:
            return []

        return [
            {
                "country": location_query["country"],
                "where": location_query["where"],
                "what_or": what_or,
            }
            for location_query in cls.build_location_queries(profile)
        ]

    @staticmethod
    def normalize_location(raw_job):
        location = raw_job.get("location")

        if not isinstance(location, dict):
            return None

        display_name = str(location.get("display_name") or "").strip()

        if display_name:
            return display_name

        area = location.get("area")

        if isinstance(area, list):
            parts = [
                str(item).strip()
                for item in area
                if str(item).strip()
            ]

            if parts:
                return ", ".join(reversed(parts))

        return None

    @classmethod
    def normalize_salary(cls, raw_job, country):
        salary_min = raw_job.get("salary_min")
        salary_max = raw_job.get("salary_max")

        if salary_min is None and salary_max is None:
            return None

        currency = cls.currency_codes.get(country, country.upper())

        def format_amount(value):
            try:
                return f"{float(value):,.0f}"
            except (TypeError, ValueError):
                return str(value)

        if salary_min is not None and salary_max is not None:
            return (
                f"{currency} {format_amount(salary_min)} - "
                f"{format_amount(salary_max)}"
            )

        if salary_min is not None:
            return f"From {currency} {format_amount(salary_min)}"

        return f"Up to {currency} {format_amount(salary_max)}"

    @staticmethod
    def normalize_employment_type(raw_job):
        title = str(raw_job.get("title") or "").lower()

        if re.search(r"\b(?:intern|internship|co-op|coop)\b", title):
            return "Internship"

        contract_type = str(
            raw_job.get("contract_type") or ""
        ).strip().lower()
        contract_time = str(
            raw_job.get("contract_time") or ""
        ).strip().lower()

        if contract_type == "contract":
            return "Contract"

        if contract_time == "full_time":
            return "Full-time"

        if contract_time == "part_time":
            return "Part-time"

        return None

    @staticmethod
    def normalize_workplace_type(raw_job, location, description):
        text = " ".join(
            [
                str(raw_job.get("title") or ""),
                str(location or ""),
                str(description or ""),
            ]
        ).lower()

        if re.search(
            r"\b(?:fully\s+)?remote\b|\bwork\s+from\s+home\b",
            text,
        ):
            return "Remote"

        if re.search(r"\bhybrid\b", text):
            return "Hybrid"

        return None

    @classmethod
    def normalize_job(cls, raw_job, country):
        posting_url = str(raw_job.get("redirect_url") or "").strip()

        if not posting_url:
            return None

        company = raw_job.get("company")

        if not isinstance(company, dict):
            company = {}

        category = raw_job.get("category")

        if not isinstance(category, dict):
            category = {}

        description = clean_html_text(raw_job.get("description"))
        location = cls.normalize_location(raw_job)
        workplace_type = cls.normalize_workplace_type(
            raw_job,
            location,
            description,
        )

        return {
            "source": cls.source_name,
            "external_id": str(raw_job.get("id") or posting_url),
            "company_name": str(
                company.get("display_name")
                or company.get("canonical_name")
                or "Unknown Company"
            ),
            "position_title": str(
                raw_job.get("title") or "Untitled Position"
            ),
            "location": location,
            "employment_type": cls.normalize_employment_type(raw_job),
            "salary": cls.normalize_salary(raw_job, country),
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": (
                [category.get("label")]
                if category.get("label")
                else []
            ),
            "offices": [],
            "is_remote": workplace_type == "Remote",
            "workplace_type": workplace_type,
            "published_at": raw_job.get("created"),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_query(cls, query):
        app_id, app_key = cls.credentials()
        country = query["country"]
        where = query.get("where")
        what_or = query["what_or"]
        cache_key = (
            country,
            str(where or "").lower(),
            what_or.lower(),
        )

        with cls._cache_lock:
            cached = cls._query_cache.get(cache_key)

            if cls.cache_is_fresh(cached):
                return list(cached["jobs"]), True, 0

        jobs = []
        requests_made = 0

        for page in range(1, cls.pages_per_query + 1):
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": cls.results_per_page,
                "what_or": what_or,
                "category": cls.category,
                "max_days_old": 30,
                "sort_by": "date",
"content-type": "application/json",
            }

            if where:
                params["where"] = where

            payload = fetch_json(
                f"{cls.api_root}/{country}/search/{page}",
                params=params,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            requests_made += 1

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Adzuna returned an unexpected response."
                )

            results = payload.get("results", [])

            if not isinstance(results, list):
                raise RuntimeError("Adzuna returned invalid results data.")

            for raw_job in results:
                if not isinstance(raw_job, dict):
                    continue

                job = cls.normalize_job(raw_job, country)

                if job is not None:
                    jobs.append(job)

            if len(results) < cls.results_per_page:
                break

        deduplicated = {}

        for job in jobs:
            key = job.get("external_id") or job.get("posting_url")

            if key:
                deduplicated[str(key)] = job

        jobs = list(deduplicated.values())

        with cls._cache_lock:
            cls._query_cache[cache_key] = {
                "fetched_at": datetime.now(timezone.utc),
                "jobs": list(jobs),
            }

        return jobs, False, requests_made

    def prepare(self, profiles):
        self._prepared = True
        self._prepared_jobs = []
        self._prepared_stats = {
            "queries": 0,
            "network_requests": 0,
            "cached_queries": 0,
            "unsupported_profiles": 0,
        }

        if not self.credentials_available():
            print(
                "ADZUNA DISABLED | Set ADZUNA_APP_ID and "
                "ADZUNA_APP_KEY to enable the source."
            )
            return []

        queries = []
        seen_queries = set()
        unsupported_profiles = 0

        for profile in profiles:
            profile_queries = self.build_profile_queries(profile)

            if not profile_queries:
                unsupported_profiles += 1
                continue

            for query in profile_queries:
                key = (
                    query["country"],
                    str(query.get("where") or "").lower(),
                    query["what_or"].lower(),
                )

                if key in seen_queries:
                    continue

                seen_queries.add(key)
                queries.append(query)

        if len(queries) > self.max_queries_per_prepare:
            print(
                "ADZUNA QUERY LIMIT | "
                f"Prepared: {len(queries)} | "
                f"Running first {self.max_queries_per_prepare} "
                "to protect API quota."
            )
            queries = queries[: self.max_queries_per_prepare]

        all_jobs = []
        network_requests = 0
        cached_queries = 0

        for query in queries:
            jobs, from_cache, requests_made = self.fetch_query(query)
            network_requests += requests_made

            if from_cache:
                cached_queries += 1

            all_jobs.extend(jobs)

            print(
                "ADZUNA QUERY | "
                f"Country: {query['country'].upper()} | "
                f"Where: {query.get('where') or 'countrywide'} | "
                f"Terms: {query['what_or']} | "
                f"Jobs: {len(jobs)} | "
                f"Cache: {'yes' if from_cache else 'no'}"
            )

        deduplicated = {}

        for job in all_jobs:
            key = job.get("external_id") or job.get("posting_url")

            if key:
                deduplicated[str(key)] = job

        self._prepared_jobs = list(deduplicated.values())
        self._prepared_stats = {
            "queries": len(queries),
            "network_requests": network_requests,
            "cached_queries": cached_queries,
            "unsupported_profiles": unsupported_profiles,
        }

        print(
            "ADZUNA SHARED FEED | "
            f"Queries: {len(queries)} | "
            f"Network requests: {network_requests} | "
            f"Cached queries: {cached_queries} | "
            f"Unique jobs: {len(self._prepared_jobs)} | "
            f"Profiles without supported country: {unsupported_profiles}"
        )

        return list(self._prepared_jobs)

    def search(self, profile, source_config=None):
        if not self._prepared:
            self.prepare([profile])

        if not self._prepared_jobs:
            print(
                "ADZUNA SEARCH COMPLETE | "
                f"Profile: {profile.name} | Matched: 0"
            )
            return []

        matching_jobs = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(job, profile)
        ]

        print(
            "ADZUNA SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: {len(self._prepared_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
