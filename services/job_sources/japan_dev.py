
import threading
from datetime import datetime, timedelta, timezone

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, post_json
from services.job_sources.job_match_service import job_matches_profile


class JapanDevJobSource(BaseJobSource):
    source_name = "Japan Dev"
    source_type = "japan_dev"
    requires_company_config = False

    application_id = "8S3J8C7YSA"
    search_api_key = "9ebc037e3e423ff4aa80a065944a2b5b"
    index_name = "Job_production"

    search_url = (
        f"https://{application_id}-dsn.algolia.net/"
        f"1/indexes/{index_name}/query"
    )

    # Cache the public search results so the 15-minute scheduler
    # does not repeatedly request the same Japan Dev job data.
    cache_duration = timedelta(hours=6)
    hits_per_page = 100

    _cached_jobs = None
    _cache_fetched_at = None
    _cache_lock = threading.Lock()

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
    def normalize_enum(value):
        if not value:
            return None

        normalized = str(value).strip()

        prefixes = (
            "employment_type_",
            "remote_level_",
            "seniority_level_",
            "candidate_location_",
            "sponsors_visas_",
            "japanese_level_",
            "english_level_",
        )

        for prefix in prefixes:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break

        return normalized.replace("_", " ").strip()

    @classmethod
    def normalize_employment_type(cls, value, is_internship):
        if is_internship:
            return "Internship"

        normalized = cls.normalize_enum(value)

        mapping = {
            "full time": "Full-time",
            "part time": "Part-time",
            "contract": "Contract",
            "temporary": "Temporary",
            "internship": "Internship",
        }

        return mapping.get(
            normalized,
            normalized.title() if normalized else None,
        )

    @classmethod
    def normalize_workplace_type(cls, value):
        normalized = cls.normalize_enum(value)

        if normalized in {
            "full",
            "full japan",
            "full worldwide",
            "remote",
        }:
            return "Remote", True

        if normalized in {
            "partial",
            "hybrid",
        }:
            return "Hybrid", True

        return "On-site", False

    @classmethod
    def normalize_visa_sponsorship(cls, value):
        normalized = cls.normalize_enum(value)

        if normalized == "yes":
            return "Yes"

        if normalized == "no":
            return "No"

        return "Unknown"

    @classmethod
    def normalize_overseas_applicant_status(
        cls,
        raw_job,
        candidate_location,
    ):
        searchable_parts = [
            candidate_location,
            raw_job.get("candidate_location"),
            raw_job.get("intro"),
            raw_job.get("details"),
            raw_job.get("requirements"),
        ]

        searchable_text = clean_html_text(
            " ".join(
                str(value or "")
                for value in searchable_parts
            )
        ).lower()

        negative_phrases = (
            "japan only",
            "residents only",
            "current residents only",
            "already in japan",
            "must reside in japan",
            "must be residing in japan",
            "currently living in japan",
            "current residents of japan",
            "apply from japan only",
            "domestic applicants only",
        )

        positive_phrases = (
            "anywhere",
            "apply from abroad",
            "overseas applicants welcome",
            "open to overseas applicants",
            "applications from overseas",
            "overseas applications accepted",
            "outside japan",
        )

        if any(
            phrase in searchable_text
            for phrase in negative_phrases
        ):
            return "No"

        if any(
            phrase in searchable_text
            for phrase in positive_phrases
        ):
            return "Yes"

        return "Unknown"


    @staticmethod
    def format_salary(minimum, maximum):
        if minimum is None and maximum is None:
            return None

        if minimum is not None and maximum is not None:
            return (
                f"JPY {minimum:,.0f} - "
                f"{maximum:,.0f} per year"
            )

        if minimum is not None:
            return f"From JPY {minimum:,.0f} per year"

        return f"Up to JPY {maximum:,.0f} per year"

    @staticmethod
    def combine_description(raw_job):
        sections = []

        section_fields = (
            ("Introduction", "intro"),
            ("Details", "details"),
            ("Requirements", "requirements"),
            ("Benefits", "benefits"),
            ("Company", "company_description"),
        )

        for heading, field_name in section_fields:
            value = clean_html_text(
                raw_job.get(field_name)
            )

            if value:
                sections.append(
                    f"{heading}\n{value}"
                )

        metadata_lines = []

        japanese_level = JapanDevJobSource.normalize_enum(
            raw_job.get("japanese_level_enum")
        )
        english_level = JapanDevJobSource.normalize_enum(
            raw_job.get("english_level_enum")
        )
        seniority = JapanDevJobSource.normalize_enum(
            raw_job.get("seniority_level")
        )
        candidate_location = JapanDevJobSource.normalize_enum(
            raw_job.get("candidate_location")
        )

        if japanese_level:
            metadata_lines.append(
                f"Japanese level: {japanese_level}"
            )

        if english_level:
            metadata_lines.append(
                f"English level: {english_level}"
            )

        if seniority:
            metadata_lines.append(
                f"Seniority: {seniority}"
            )

        if candidate_location:
            metadata_lines.append(
                f"Candidate location: {candidate_location}"
            )

        if metadata_lines:
            sections.append(
                "Job conditions\n"
                + "\n".join(metadata_lines)
            )

        return "\n\n".join(sections) or None

    @staticmethod
    def build_posting_url(raw_job):
        slug = str(raw_job.get("slug") or "").strip()

        if not slug:
            return None

        company = raw_job.get("company") or {}
        company_slug = ""

        if isinstance(company, dict):
            company_slug = str(
                company.get("slug") or ""
            ).strip()

        if company_slug:
            return (
                "https://japan-dev.com/jobs/"
                f"{company_slug}/{slug}"
            )

        return f"https://japan-dev.com/jobs/{slug}"

    def fetch_page(self, page_number):
        headers = {
            "X-Algolia-Application-Id": (
                self.application_id
            ),
            "X-Algolia-API-Key": self.search_api_key,
        }

        payload = {
            "query": "",
            "page": page_number,
            "hitsPerPage": self.hits_per_page,
            "attributesToRetrieve": [
                "id",
                "objectID",
                "title",
                "intro",
                "benefits",
                "skills",
                "skill_names",
                "alternate_skill_names",
                "company_description",
                "location",
                "details",
                "japanese_level",
                "english_level",
                "company_name",
                "slug",
                "salary_min",
                "salary_max",
                "requirements",
                "application_url",
                "job_post_date",
                "created_at",
                "updated_at",
                "is_internship",
                "is_japanese_only",
                "japanese_level_enum",
                "english_level_enum",
                "published_at",
                "remote_level",
                "employment_type",
                "seniority_level",
                "candidate_location",
                "sponsors_visas",
                "company",
                "job_type_names",
                "company_tag_names",
            ],
        }

        response = post_json(
            self.search_url,
            json_data=payload,
            headers=headers,
        )

        if not isinstance(response, dict):
            raise RuntimeError(
                "Japan Dev returned an unexpected response."
            )

        hits = response.get("hits", [])

        if not isinstance(hits, list):
            raise RuntimeError(
                "Japan Dev returned invalid jobs data."
            )

        return response

    def fetch_jobs(self):
        collected_jobs = []
        page_number = 0
        total_pages = None

        while total_pages is None or page_number < total_pages:
            response = self.fetch_page(page_number)
            hits = response.get("hits", [])

            if total_pages is None:
                total_pages = response.get("nbPages", 0)

            collected_jobs.extend(
                hit
                for hit in hits
                if isinstance(hit, dict)
            )
            
            if page_number == 0:
                print(
                    "JAPAN DEV DATE DEBUG"
                )

                for debug_job in hits[:10]:
                    print(
                        {
                            "title": debug_job.get("title"),
                            "job_post_date": (
                                debug_job.get("job_post_date")
                            ),
                            "published_at": (
                                debug_job.get("published_at")
                            ),
                            "created_at": (
                                debug_job.get("created_at")
                            ),
                            "updated_at": (
                                debug_job.get("updated_at")
                            ),
                        }
                    )

            print(
                "JAPAN DEV FETCH PROGRESS | "
                f"Page: {page_number + 1}/"
                f"{total_pages or 1} | "
                f"Jobs collected: {len(collected_jobs)}"
            )

            if not hits:
                break

            page_number += 1

        return collected_jobs

    def normalize_job(self, raw_job):
        posting_url = self.build_posting_url(raw_job)
        workplace_type, is_remote = (
            self.normalize_workplace_type(
                raw_job.get("remote_level")
            )
        )

        skill_names = raw_job.get("skill_names") or []
        job_type_names = (
            raw_job.get("job_type_names")
            or []
        )
        company_tag_names = (
            raw_job.get("company_tag_names")
            or []
        )

        departments = []

        for value in (
            list(skill_names)
            + list(job_type_names)
            + list(company_tag_names)
        ):
            normalized = str(value or "").strip()

            if normalized and normalized not in departments:
                departments.append(normalized)

        seniority = self.normalize_enum(
            raw_job.get("seniority_level")
        )

        if seniority:
            departments.append(
                f"Seniority: {seniority}"
            )

        application_url = str(
            raw_job.get("application_url") or ""
        ).strip()

        candidate_location = self.normalize_enum(
            raw_job.get("candidate_location")
        )
        remote_level = self.normalize_enum(
            raw_job.get("remote_level")
        )

        remote_candidate_scope = None
        remote_allowed_locations = []

        if workplace_type == "Remote":
            # Japan Dev separates the workplace arrangement
            # from where the candidate is allowed to live.
            if (
                remote_level == "full japan"
                or candidate_location == "japan only"
            ):
                remote_candidate_scope = (
                    "selected_locations"
                )
                remote_allowed_locations = ["Japan"]
            elif candidate_location == "anywhere":
                remote_candidate_scope = "worldwide"
            else:
                # Do not guess that an unspecified Japan Dev
                # remote job can be performed outside Japan.
                remote_candidate_scope = (
                    "selected_locations"
                )
                remote_allowed_locations = ["Japan"]

        return {
            "source": self.source_name,
            "external_id": (
                str(
                    raw_job.get("objectID")
                    or raw_job.get("id")
                    or raw_job.get("slug")
                )
            ),
            "company_name": (
                raw_job.get("company_name")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("title")
                or "Untitled Position"
            ),
            "location": (
                raw_job.get("location")
                or "Japan"
            ),
            "employment_type": (
                self.normalize_employment_type(
                    raw_job.get("employment_type"),
                    bool(raw_job.get("is_internship")),
                )
            ),
            "salary": self.format_salary(
                raw_job.get("salary_min"),
                raw_job.get("salary_max"),
            ),
            "visa_sponsorship": (
                self.normalize_visa_sponsorship(
                    raw_job.get("sponsors_visas")
                )
            ),
            "overseas_applicant_status": (
                self.normalize_overseas_applicant_status(
                    raw_job,
                    candidate_location,
                )
            ),
            # Preserve the Japan Dev listing as the canonical source page.
            "posting_url": posting_url,
            "apply_url": application_url or posting_url,
            "job_description": self.combine_description(
                raw_job
            ),
            "departments": departments,
            "offices": [],
            "is_remote": is_remote,
            "workplace_type": workplace_type,
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "candidate_location": candidate_location,
            # Japan Dev provides a dedicated seniority field.
            # The shared matcher trusts this before description text.
            "experience_level": seniority,
            "published_at": (
                # Japan Dev's published_at value can describe when
                # the Algolia record was first published rather than
                # the job board's visible posting date. Prefer the
                # dedicated job_post_date for profile age filtering.
                raw_job.get("job_post_date")
                or raw_job.get("published_at")
                or raw_job.get("updated_at")
                or raw_job.get("created_at")
            ),
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
                    "JAPAN DEV CACHE | "
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
            source_class._cache_fetched_at = datetime.now(
                timezone.utc
            )

            print(
                "JAPAN DEV FEED | "
                f"Fetched {len(normalized_jobs)} jobs."
            )

            return list(normalized_jobs)

    def search(self, profile, source_config=None):
        jobs = self.get_cached_jobs()

        matching_jobs = [
            job
            for job in jobs
            if job_matches_profile(job, profile)
        ]

        print(
            f"JAPAN DEV SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
