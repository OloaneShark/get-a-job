
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile
from services.job_sources.source_utils import extract_workable_account_subdomain


class WorkableJobSource(BaseJobSource):
    source_name = "Workable"
    source_type = "workable"
    requires_company_config = True

    public_base_url = "https://www.workable.com/api/accounts"
    cache_duration = timedelta(hours=1)

    _cache_lock = threading.Lock()
    _account_cache = {}

    @classmethod
    def _cache_get(cls, key):
        with cls._cache_lock:
            item = cls._account_cache.get(key)
            if not item:
                return None

            fetched_at = item.get("fetched_at")
            if (
                fetched_at is None
                or datetime.now(timezone.utc) - fetched_at >= cls.cache_duration
            ):
                cls._account_cache.pop(key, None)
                return None

            return item.get("value")

    @classmethod
    def _cache_set(cls, key, value):
        with cls._cache_lock:
            cls._account_cache[key] = {
                "fetched_at": datetime.now(timezone.utc),
                "value": value,
            }
        return value

    @staticmethod
    def _text(value):
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def fetch_account_payload(cls, account_subdomain):
        account_subdomain = extract_workable_account_subdomain(account_subdomain)

        cached = cls._cache_get(account_subdomain)
        if cached is not None:
            jobs = cached.get("jobs") or []
            print(
                "WORKABLE CACHE | "
                f"Account: {account_subdomain} | "
                f"Raw jobs: {len(jobs)}"
            )
            return cached

        payload = fetch_json(
            f"{cls.public_base_url}/{account_subdomain}",
            params={"details": "true"},
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Workable returned an unexpected response for "
                f"account '{account_subdomain}'."
            )

        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RuntimeError(
                "Workable returned invalid jobs data for "
                f"account '{account_subdomain}'."
            )

        print(
            "WORKABLE FETCH | "
            f"Account: {account_subdomain} | "
            f"Raw jobs: {len(jobs)}"
        )

        return cls._cache_set(account_subdomain, payload)

    @classmethod
    def fetch_company_jobs(cls, account_subdomain):
        return cls.fetch_account_payload(account_subdomain).get("jobs") or []

    @classmethod
    def _normalize_employment_type(cls, value, title):
        value = cls._text(value).casefold()
        title = cls._text(title).casefold()

        if "intern" in title and value in {"", "other"}:
            return "Internship"

        return {
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
            "intern": "Internship",
            "internship": "Internship",
            "freelance": "Freelance",
        }.get(value)

    @classmethod
    def _normalize_experience(cls, value, title):
        value = cls._text(value).casefold()
        title = cls._text(title).casefold()

        if "intern" in title or value in {"intern", "internship"}:
            return "intern"

        if value in {
            "entry",
            "entry level",
            "entry-level",
            "associate",
        }:
            return "entry"

        if value in {
            "mid",
            "mid level",
            "mid-level",
            "intermediate",
        }:
            return "mid"

        if value in {
            "mid-senior level",
            "mid senior level",
            "mid/senior level",
        }:
            return ["mid", "senior"]

        if value in {
            "senior",
            "senior level",
            "senior-level",
        }:
            return "senior"

        if value in {"director", "executive", "manager"}:
            return "manager"

        return None

    @classmethod
    def _detect_workplace_type(cls, jobs, title, description):
        explicit_types = {
            cls._text(job.get("workplace_type"))
            .casefold()
            .replace("_", "-")
            for job in jobs
            if cls._text(job.get("workplace_type"))
        }

        if "hybrid" in explicit_types:
            return "Hybrid"

        if "remote" in explicit_types:
            return "Remote"

        if explicit_types.intersection({"on-site", "onsite", "on site"}):
            return "On-site"

        if any(job.get("telecommuting") is True for job in jobs):
            return "Remote"

        searchable = " ".join(
            (
                cls._text(title),
                cls._text(description)[:2500],
            )
        ).casefold()

        hybrid_patterns = (
            r"\bhybrid\s+role\b",
            r"\bhybrid\s+position\b",
            r"\bhybrid\s+working\b",
            r"\bhybrid\s+work\s+model\b",
            r"\bhybrid\s+schedule\b",
            r"\bwork(?:ing)?\s+hybrid\b",
        )

        if any(re.search(pattern, searchable) for pattern in hybrid_patterns):
            return "Hybrid"

        return "On-site"

    @classmethod
    def _format_location_dict(cls, value):
        if not isinstance(value, dict):
            return None

        city = cls._text(value.get("city"))
        state = cls._text(
            value.get("state")
            or value.get("state_name")
            or value.get("state_code")
            or value.get("region")
            or value.get("subregion")
        )
        country = cls._text(
            value.get("country")
            or value.get("country_name")
        )

        parts = []
        for item in (city, state, country):
            if item and item not in parts:
                parts.append(item)

        return ", ".join(parts) or None

    @classmethod
    def _collect_locations(cls, jobs):
        locations = []
        seen = set()

        def add(value):
            value = cls._text(value)
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                locations.append(value)

        for job in jobs:
            top_level = cls._format_location_dict(
                {
                    "city": job.get("city"),
                    "state": job.get("state"),
                    "country": job.get("country"),
                }
            )
            if top_level:
                add(top_level)

            nested = job.get("locations") or []
            if isinstance(nested, list):
                for item in nested:
                    location = cls._format_location_dict(item)
                    if location:
                        add(location)

        return locations

    @classmethod
    def _first_nonempty(cls, jobs, field):
        for job in jobs:
            value = job.get(field)
            if value is None:
                continue

            if isinstance(value, str):
                if value.strip():
                    return value
            else:
                return value

        return None

    @classmethod
    def _longest_text(cls, jobs, field):
        values = [
            str(job.get(field) or "").strip()
            for job in jobs
            if str(job.get(field) or "").strip()
        ]
        return max(values, key=len) if values else None

    @classmethod
    def _group_jobs(cls, raw_jobs):
        groups = {}
        skipped = 0

        for job in raw_jobs:
            if not isinstance(job, dict):
                skipped += 1
                continue

            shortcode = cls._text(job.get("shortcode"))
            if shortcode:
                key = ("shortcode", shortcode.casefold())
            else:
                fallback = (
                    cls._text(job.get("shortlink"))
                    or cls._text(job.get("url"))
                    or cls._text(job.get("application_url"))
                )
                if not fallback:
                    skipped += 1
                    continue
                key = ("fallback", fallback.casefold())

            groups.setdefault(key, []).append(job)

        return groups, skipped

    @classmethod
    def _normalize_group(cls, jobs, company_name, account_subdomain):
        title = cls._text(cls._first_nonempty(jobs, "title"))
        if not title:
            return None

        shortcode = cls._text(cls._first_nonempty(jobs, "shortcode"))
        posting_url = (
            cls._text(cls._first_nonempty(jobs, "shortlink"))
            or cls._text(cls._first_nonempty(jobs, "url"))
        )
        apply_url = (
            cls._text(cls._first_nonempty(jobs, "application_url"))
            or posting_url
        )

        if not posting_url:
            return None

        description = clean_html_text(
            cls._longest_text(jobs, "description")
        )
        workplace_type = cls._detect_workplace_type(
            jobs,
            title,
            description,
        )
        locations = cls._collect_locations(jobs)

        if workplace_type == "Remote":
            if locations:
                location = "Remote | " + " | ".join(locations)
                location_source = "workable_remote_locations"
                location_confidence = 0.8
                remote_candidate_scope = "selected_locations"
                remote_allowed_locations = list(locations)
            else:
                location = "Remote"
                location_source = "unspecified"
                location_confidence = 0.4
                remote_candidate_scope = None
                remote_allowed_locations = []
        else:
            location = " | ".join(locations) if locations else "Unknown"
            location_source = (
                "workable_locations" if locations else "unknown"
            )
            location_confidence = 1.0 if locations else 0.0
            remote_candidate_scope = None
            remote_allowed_locations = []

        experience_level = cls._normalize_experience(
            cls._first_nonempty(jobs, "experience"),
            title,
        )
        employment_type = cls._normalize_employment_type(
            cls._first_nonempty(jobs, "employment_type"),
            title,
        )
        department = cls._text(
            cls._first_nonempty(jobs, "department")
        )
        published_at = (
            cls._first_nonempty(jobs, "published_on")
            or cls._first_nonempty(jobs, "created_at")
        )

        external_key = shortcode or re.sub(
            r"[^a-zA-Z0-9]+",
            "-",
            posting_url,
        ).strip("-")

        return {
            "source": cls.source_name,
            "external_id": f"{account_subdomain}:{external_key}",
            "company_name": company_name,
            "position_title": title,
            "location": location,
            "location_source": location_source,
            "location_confidence": location_confidence,
            "employment_type": employment_type,
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": description,
            "departments": [department] if department else [],
            "offices": list(locations),
            "is_remote": workplace_type in {"Remote", "Hybrid"},
            "workplace_type": workplace_type,
            "remote_candidate_scope": remote_candidate_scope,
            "remote_allowed_locations": remote_allowed_locations,
            "published_at": published_at,
            "experience_level": experience_level,
            "seniority_level": experience_level,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def normalize_account_jobs(
        cls,
        raw_jobs,
        company_name,
        account_subdomain,
    ):
        groups, skipped = cls._group_jobs(raw_jobs)
        normalized = []

        for jobs in groups.values():
            job = cls._normalize_group(
                jobs,
                company_name,
                account_subdomain,
            )
            if job is not None:
                normalized.append(job)

        duplicates_merged = max(
            0,
            len(raw_jobs) - len(groups) - skipped,
        )

        print(
            "WORKABLE FEED | "
            f"Account: {account_subdomain} | "
            f"Raw: {len(raw_jobs)} | "
            f"Unique: {len(normalized)} | "
            f"Duplicates merged: {duplicates_merged} | "
            f"Skipped: {skipped}"
        )

        return normalized

    def fetch_validation_jobs(self, account_subdomain):
        account_subdomain = extract_workable_account_subdomain(
            account_subdomain
        )
        payload = self.fetch_account_payload(account_subdomain)
        company_name = self._text(payload.get("name")) or account_subdomain

        return self.normalize_account_jobs(
            payload.get("jobs") or [],
            company_name,
            account_subdomain,
        )

    def search_company(
        self,
        profile,
        account_subdomain,
        company_name,
    ):
        account_subdomain = extract_workable_account_subdomain(
            account_subdomain
        )
        payload = self.fetch_account_payload(account_subdomain)

        resolved_company_name = (
            self._text(company_name)
            or self._text(payload.get("name"))
            or account_subdomain
        )

        jobs = self.normalize_account_jobs(
            payload.get("jobs") or [],
            resolved_company_name,
            account_subdomain,
        )

        matched_jobs = [
            job
            for job in jobs
            if job_matches_profile(job, profile)
        ]

        print(
            "WORKABLE SEARCH COMPLETE | "
            f"Account: {account_subdomain} | "
            f"Evaluated: {len(jobs)} | "
            f"Matched: {len(matched_jobs)}"
        )

        return matched_jobs

    def search(self, profile, source_config=None):
        if source_config is None:
            raise ValueError(
                "Workable requires a company source configuration."
            )

        return self.search_company(
            profile=profile,
            account_subdomain=source_config.source_identifier,
            company_name=source_config.company_name,
        )
