
import re
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import (
    job_matches_profile,
    matches_role_title,
)
from services.job_sources.source_utils import (
    extract_bamboohr_company_subdomain,
)


class BambooHRJobSource(BaseJobSource):
    source_name = "BambooHR"
    source_type = "bamboohr"
    requires_company_config = True

    cache_duration = timedelta(minutes=30)

    _cache_lock = threading.Lock()
    _listing_cache = {}
    _detail_cache = {}
    _company_cache = {}

    @classmethod
    def cache_get(cls, cache, key):
        with cls._cache_lock:
            item = cache.get(key)

            if not item:
                return None

            fetched_at = item.get("fetched_at")

            if (
                fetched_at is None
                or (
                    datetime.now(timezone.utc)
                    - fetched_at
                ) >= cls.cache_duration
            ):
                cache.pop(key, None)
                return None

            return item.get("value")

    @classmethod
    def cache_set(cls, cache, key, value):
        with cls._cache_lock:
            cache[key] = {
                "fetched_at": datetime.now(timezone.utc),
                "value": value,
            }

        return value

    @staticmethod
    def company_base_url(company_subdomain):
        return f"https://{company_subdomain}.bamboohr.com"

    @classmethod
    def fetch_company_info(cls, company_subdomain):
        company_subdomain = extract_bamboohr_company_subdomain(
            company_subdomain
        )

        cached = cls.cache_get(
            cls._company_cache,
            company_subdomain,
        )

        if cached is not None:
            return cached

        payload = fetch_json(
            (
                f"{cls.company_base_url(company_subdomain)}"
                "/careers/company-info"
            ),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "BambooHR returned an unexpected company-info response."
            )

        result = payload.get("result")

        if not isinstance(result, dict):
            raise RuntimeError(
                "BambooHR returned invalid company-info data."
            )

        return cls.cache_set(
            cls._company_cache,
            company_subdomain,
            result,
        )

    @classmethod
    def fetch_company_jobs(cls, company_subdomain):
        company_subdomain = extract_bamboohr_company_subdomain(
            company_subdomain
        )

        cached = cls.cache_get(
            cls._listing_cache,
            company_subdomain,
        )

        if cached is not None:
            print(
                "BAMBOOHR LIST CACHE | "
                f"Company: {company_subdomain} | "
                f"Jobs: {len(cached)}"
            )
            return cached

        payload = fetch_json(
            (
                f"{cls.company_base_url(company_subdomain)}"
                "/careers/list"
            ),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "BambooHR returned an unexpected careers-list response."
            )

        jobs = payload.get("result")

        if not isinstance(jobs, list):
            raise RuntimeError(
                "BambooHR returned invalid careers-list job data."
            )

        print(
            "BAMBOOHR LIST | "
            f"Company: {company_subdomain} | "
            f"Jobs: {len(jobs)}"
        )

        return cls.cache_set(
            cls._listing_cache,
            company_subdomain,
            jobs,
        )

    @classmethod
    def fetch_job_detail(
        cls,
        company_subdomain,
        job_id,
    ):
        company_subdomain = extract_bamboohr_company_subdomain(
            company_subdomain
        )
        job_id = str(job_id or "").strip()

        if not job_id:
            raise ValueError("A BambooHR job ID is required.")

        cache_key = (
            company_subdomain,
            job_id,
        )

        cached = cls.cache_get(
            cls._detail_cache,
            cache_key,
        )

        if cached is not None:
            return cached

        payload = fetch_json(
            (
                f"{cls.company_base_url(company_subdomain)}"
                f"/careers/{job_id}/detail"
            ),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "BambooHR returned an unexpected "
                f"detail response for job {job_id}."
            )

        result = payload.get("result")

        if not isinstance(result, dict):
            raise RuntimeError(
                "BambooHR returned invalid detail data "
                f"for job {job_id}."
            )

        job = result.get("jobOpening")

        if not isinstance(job, dict):
            raise RuntimeError(
                "BambooHR detail response did not contain "
                f"a jobOpening object for job {job_id}."
            )

        return cls.cache_set(
            cls._detail_cache,
            cache_key,
            job,
        )

    @staticmethod
    def normalized_text(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @classmethod
    def normalize_employment_type(cls, *values):
        text = " ".join(
            cls.normalized_text(value)
            for value in values
            if cls.normalized_text(value)
        ).casefold()

        if not text:
            return None

        if "intern" in text:
            return "Internship"

        if (
            "part-time" in text
            or "part time" in text
            or "parttime" in text
        ):
            return "Part-time"

        if "contract" in text:
            return "Contract"

        if (
            "temporary" in text
            or "seasonal" in text
            or re.search(
                r"(?<!\w)temp(?!\w)",
                text,
            )
        ):
            return "Temporary"

        if (
            "full-time" in text
            or "full time" in text
            or "fulltime" in text
        ):
            return "Full-time"

        return None

    @classmethod
    def normalize_experience_level(cls, value):
        text = cls.normalized_text(value).casefold()

        if not text:
            return None

        if (
            "intern" in text
            or "student" in text
        ):
            return "intern"

        if (
            "entry" in text
            or "new grad" in text
            or "graduate" in text
        ):
            return "entry"

        if "junior" in text:
            return "junior"

        if (
            "mid-level" in text
            or "mid level" in text
            or "intermediate" in text
        ):
            return "mid"

        if (
            "manager" in text
            or "supervisor" in text
            or "executive" in text
            or "director" in text
        ):
            return "manager"

        # BambooHR's generic "Experienced" value is not forced into
        # mid/senior. The shared matcher can infer explicit years
        # from the full description instead.
        return None

    @classmethod
    def normalize_location_type(
        cls,
        value,
        title=None,
        is_remote=None,
    ):
        try:
            number = int(value)
        except (
            TypeError,
            ValueError,
        ):
            number = None

        if number == 0:
            return "On-site"

        if number == 1:
            return "Remote"

        if number == 2:
            return "Hybrid"

        if is_remote is True:
            return "Remote"

        title_text = cls.normalized_text(title).casefold()

        if "hybrid" in title_text:
            return "Hybrid"

        if "remote" in title_text:
            return "Remote"

        return "On-site"

    @classmethod
    def location_parts(cls, value):
        if not isinstance(value, dict):
            return []

        parts = []

        for key in (
            "city",
            "state",
            "country",
            "addressCountry",
        ):
            item = cls.normalized_text(
                value.get(key)
            )

            if (
                item
                and item not in parts
            ):
                parts.append(item)

        return parts

    @classmethod
    def physical_location(cls, job):
        primary = cls.location_parts(
            job.get("location")
        )

        if primary:
            return ", ".join(primary)

        ats = cls.location_parts(
            job.get("atsLocation")
        )

        if ats:
            return ", ".join(ats)

        return None

    @classmethod
    def location_metadata(
        cls,
        job,
        workplace_type,
    ):
        if workplace_type == "Remote":
            return {
                "location": "Remote",
                "location_source": "bamboohr_location_type",
                "location_confidence": 0.4,
                "remote_candidate_scope": None,
                "remote_allowed_locations": [],
                "is_remote": True,
            }

        location = cls.physical_location(job)

        return {
            "location": location or "Unknown",
            "location_source": (
                "bamboohr_location"
                if location
                else "unknown"
            ),
            "location_confidence": (
                1.0
                if location
                else 0.0
            ),
            "remote_candidate_scope": None,
            "remote_allowed_locations": [],
            "is_remote": (
                workplace_type
                in {
                    "Remote",
                    "Hybrid",
                }
            ),
        }

    @classmethod
    def posting_url(
        cls,
        company_subdomain,
        job_id,
        job=None,
    ):
        if isinstance(job, dict):
            share_url = cls.normalized_text(
                job.get("jobOpeningShareUrl")
            )

            if share_url:
                return share_url

        return (
            f"{cls.company_base_url(company_subdomain)}"
            f"/careers/{job_id}"
        )

    @classmethod
    def normalize_listing_job(
        cls,
        raw_job,
        company_name,
        company_subdomain,
    ):
        if not isinstance(raw_job, dict):
            return None

        raw_id = raw_job.get("id")

        if raw_id is None:
            return None

        job_id = str(raw_id).strip()
        title = cls.normalized_text(
            raw_job.get("jobOpeningName")
        )

        if not title:
            return None

        workplace_type = cls.normalize_location_type(
            raw_job.get("locationType"),
            title=title,
            is_remote=raw_job.get("isRemote"),
        )

        location_data = cls.location_metadata(
            raw_job,
            workplace_type,
        )

        posting_url = cls.posting_url(
            company_subdomain,
            job_id,
            raw_job,
        )

        department = cls.normalized_text(
            raw_job.get("departmentLabel")
        )

        return {
            "source": cls.source_name,
            "external_id": (
                f"{company_subdomain}:{job_id}"
            ),
            "company_name": company_name,
            "position_title": title,
            "location": location_data["location"],
            "location_source": location_data["location_source"],
            "location_confidence": location_data["location_confidence"],
            "employment_type": cls.normalize_employment_type(
                raw_job.get("employmentStatusLabel"),
                raw_job.get("employmentType"),
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": None,
            "departments": [department] if department else [],
            "offices": [],
            "is_remote": location_data["is_remote"],
            "workplace_type": workplace_type,
            "remote_candidate_scope": (
                location_data["remote_candidate_scope"]
            ),
            "remote_allowed_locations": (
                location_data["remote_allowed_locations"]
            ),
            "published_at": None,
            "experience_level": None,
            "seniority_level": None,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def normalize_detail_job(
        cls,
        detail,
        listing_job,
        company_name,
        company_subdomain,
        job_id,
    ):
        if not isinstance(detail, dict):
            return None

        title = (
            cls.normalized_text(
                detail.get("jobOpeningName")
            )
            or listing_job.get("position_title")
        )

        if not title:
            return None

        workplace_type = cls.normalize_location_type(
            detail.get("locationType"),
            title=title,
        )

        location_data = cls.location_metadata(
            detail,
            workplace_type,
        )

        description = clean_html_text(
            detail.get("description")
        )

        experience_level = (
            cls.normalize_experience_level(
                detail.get("minimumExperience")
            )
        )

        posting_url = cls.posting_url(
            company_subdomain,
            job_id,
            detail,
        )

        department = cls.normalized_text(
            detail.get("departmentLabel")
        )

        return {
            "source": cls.source_name,
            "external_id": (
                f"{company_subdomain}:{job_id}"
            ),
            "company_name": company_name,
            "position_title": title,
            "location": location_data["location"],
            "location_source": location_data["location_source"],
            "location_confidence": location_data["location_confidence"],
            "employment_type": (
                cls.normalize_employment_type(
                    detail.get("employmentStatusLabel"),
                    detail.get("employmentType"),
                )
                or listing_job.get("employment_type")
            ),
            "salary": (
                cls.normalized_text(
                    detail.get("compensation")
                )
                or None
            ),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": [department] if department else [],
            "offices": [],
            "is_remote": location_data["is_remote"],
            "workplace_type": workplace_type,
            "remote_candidate_scope": (
                location_data["remote_candidate_scope"]
            ),
            "remote_allowed_locations": (
                location_data["remote_allowed_locations"]
            ),
            "published_at": detail.get("datePosted"),
            "experience_level": experience_level,
            "seniority_level": experience_level,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    def fetch_validation_jobs(
        self,
        company_subdomain,
    ):
        company_subdomain = extract_bamboohr_company_subdomain(
            company_subdomain
        )

        company_info = self.fetch_company_info(
            company_subdomain
        )

        company_name = (
            self.normalized_text(
                company_info.get("name")
            )
            or company_subdomain
        )

        jobs = []

        for raw_job in self.fetch_company_jobs(
            company_subdomain
        ):
            job = self.normalize_listing_job(
                raw_job,
                company_name,
                company_subdomain,
            )

            if job is not None:
                jobs.append(job)

        return jobs

    def search_company(
        self,
        profile,
        company_subdomain,
        company_name,
    ):
        company_subdomain = extract_bamboohr_company_subdomain(
            company_subdomain
        )

        if not company_name or not str(
            company_name
        ).strip():
            raise ValueError(
                "A company name is required."
            )

        company_name = str(
            company_name
        ).strip()

        listing_pairs = []

        for raw_job in self.fetch_company_jobs(
            company_subdomain
        ):
            normalized = self.normalize_listing_job(
                raw_job,
                company_name,
                company_subdomain,
            )

            if normalized is not None:
                listing_pairs.append(
                    (
                        raw_job,
                        normalized,
                    )
                )

        role_candidates = [
            (
                raw_job,
                listing_job,
            )
            for (
                raw_job,
                listing_job,
            )
            in listing_pairs
            if matches_role_title(
                listing_job,
                profile,
            )
        ]

        print(
            "BAMBOOHR PRE-DETAIL FILTER | "
            f"Company: {company_subdomain} | "
            f"Listings: {len(listing_pairs)} | "
            f"Role candidates: {len(role_candidates)}"
        )

        normalized_details = []
        detail_errors = 0

        for (
            raw_job,
            listing_job,
        ) in role_candidates:
            raw_id = raw_job.get("id")

            if raw_id is None:
                continue

            job_id = str(raw_id).strip()

            try:
                detail = self.fetch_job_detail(
                    company_subdomain,
                    job_id,
                )

                job = self.normalize_detail_job(
                    detail,
                    listing_job,
                    company_name,
                    company_subdomain,
                    job_id,
                )

            except Exception as error:
                detail_errors += 1

                print(
                    "BAMBOOHR DETAIL FAILED | "
                    f"Company: {company_subdomain} | "
                    f"Job: {job_id} | "
                    f"Error: {error}"
                )
                continue

            if (
                job is not None
                and job.get("posting_url")
            ):
                normalized_details.append(job)

        if (
            role_candidates
            and not normalized_details
            and detail_errors
            == len(role_candidates)
        ):
            raise RuntimeError(
                "BambooHR detail requests failed "
                "for every role candidate."
            )

        matched_jobs = [
            job
            for job in normalized_details
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "BAMBOOHR SEARCH COMPLETE | "
            f"Company: {company_subdomain} | "
            f"Listings: {len(listing_pairs)} | "
            f"Role candidates: {len(role_candidates)} | "
            f"Details normalized: {len(normalized_details)} | "
            f"Detail errors: {detail_errors} | "
            f"Matched: {len(matched_jobs)}"
        )

        return matched_jobs

    def search(
        self,
        profile,
        source_config=None,
    ):
        if source_config is None:
            raise ValueError(
                "BambooHR requires a company "
                "source configuration."
            )

        return self.search_company(
            profile=profile,
            company_subdomain=(
                source_config.source_identifier
            ),
            company_name=(
                source_config.company_name
            ),
        )
