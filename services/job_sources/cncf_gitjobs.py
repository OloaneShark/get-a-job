
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import fetch_html
from services.job_sources.job_match_service import (
    collect_match_diagnostics,
    format_match_diagnostics,
    job_matches_profile,
)


class CNCFGitJobsSource(BaseJobSource):
    source_name = "CNCF GitJobs"
    source_type = "cncf_gitjobs"
    requires_company_config = False

    base_url = "https://gitjobs.dev/"
    cache_duration = timedelta(hours=1)
    max_workers = 4

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None

    def __init__(self):
        self._prepared_jobs = None
        self._prepared_stats = None

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

    @staticmethod
    def normalize_space(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @classmethod
    def normalized_lines(cls, root):
        return [
            cls.normalize_space(value)
            for value in root.stripped_strings
            if cls.normalize_space(value)
        ]

    @classmethod
    def discover_job_ids(cls):
        html = fetch_html(
            cls.base_url,
            params={
                "limit": 100,
            },
            timeout=30,
        )
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        job_ids = []
        seen = set()

        for element in soup.find_all(
            attrs={
                "data-job-id": True,
            }
        ):
            job_id = cls.normalize_space(
                element.get(
                    "data-job-id"
                )
            ).lower()

            if not re.fullmatch(
                r"[0-9a-f]{8}-"
                r"[0-9a-f]{4}-"
                r"[0-9a-f]{4}-"
                r"[0-9a-f]{4}-"
                r"[0-9a-f]{12}",
                job_id,
            ):
                continue

            if job_id in seen:
                continue

            seen.add(job_id)
            job_ids.append(job_id)

        if not job_ids:
            for match in re.findall(
                r"/section/jobs/"
                r"([0-9a-fA-F-]{36})",
                html,
                flags=re.IGNORECASE,
            ):
                job_id = str(
                    match
                ).strip().lower()

                if (
                    not job_id
                    or job_id in seen
                ):
                    continue

                seen.add(job_id)
                job_ids.append(job_id)

        print(
            "CNCF GITJOBS DISCOVERY | "
            f"Unique job IDs: {len(job_ids)}"
        )

        return job_ids

    @classmethod
    def detail_url(cls, job_id):
        return (
            f"{cls.base_url}"
            f"?job_id={job_id}"
        )

    @classmethod
    def detail_section_url(
        cls,
        job_id,
    ):
        return urljoin(
            cls.base_url,
            f"section/jobs/{job_id}",
        )

    @classmethod
    def find_detail_root(cls, soup):
        return (
            soup.find(
                id="preview-content"
            )
            or soup
        )

    @classmethod
    def find_published_index(cls, lines):
        for index, value in enumerate(
            lines
        ):
            if value.lower() != "published":
                continue

            if index + 1 >= len(lines):
                continue

            if re.fullmatch(
                r"\d{4}-\d{2}-\d{2}",
                lines[index + 1],
            ):
                return index

        return None

    @classmethod
    def detail_header_lines(
        cls,
        lines,
        published_index,
    ):
        if published_index is None:
            return []

        start = 0

        for index in range(
            published_index - 1,
            -1,
            -1,
        ):
            if (
                lines[index].lower()
                == "close modal"
            ):
                start = index + 1
                break

        header = lines[
            start:published_index
        ]

        ignored = {
            "first",
            "prev",
            "next",
            "last",
            "close modal",
            "share this job",
            "job link copied to clipboard!",
            "get embed code",
        }

        return [
            value
            for value in header
            if value.lower() not in ignored
        ]

    @classmethod
    def extract_company_title(
        cls,
        detail_root,
        lines,
        published_index,
    ):
        title_element = detail_root.find(
            attrs={
                "data-testid": (
                    "preview-job-title"
                )
            }
        )

        if title_element is not None:
            title = cls.normalize_space(
                title_element.get_text(
                    " ",
                    strip=True,
                )
            )

            company_element = (
                title_element
                .find_previous_sibling(
                    "div"
                )
            )

            company = cls.normalize_space(
                company_element.get_text(
                    " ",
                    strip=True,
                )
                if company_element is not None
                else ""
            )

            if company and title:
                return company, title

        header = (
            lines[:published_index]
            if published_index is not None
            else []
        )

        header = [
            value
            for value in header
            if value.lower()
            not in {
                "remote",
                "hybrid",
                "on-site",
                "onsite",
            }
        ]

        if len(header) >= 2:
            return header[0], header[1]

        return (
            "Unknown Company",
            "Untitled Position",
        )

    @classmethod
    def extract_salary(
        cls,
        lines,
    ):
        salary = cls.extract_section(
            lines,
            "Salary",
            (
                "Location",
                "Open source time",
                "Upstream projects time",
                "Apply",
                "Share this job",
                "Job description",
            ),
        )

        if not salary:
            return None

        normalized = cls.normalize_space(
            salary
        )

        if (
            not normalized
            or normalized.lower()
            == "not provided"
        ):
            return None

        return normalized

    @classmethod
    def extract_labeled_value(
        cls,
        lines,
        label,
    ):
        lowered_label = label.lower()

        for index, value in enumerate(
            lines
        ):
            if value.lower() != lowered_label:
                continue

            if index + 1 < len(lines):
                candidate = cls.normalize_space(
                    lines[index + 1]
                )

                if candidate:
                    return candidate

        return None

    @classmethod
    def extract_section(
        cls,
        lines,
        label,
        stop_labels,
    ):
        lowered_label = label.lower()
        lowered_stops = {
            value.lower()
            for value in stop_labels
        }

        for index, value in enumerate(
            lines
        ):
            if value.lower() != lowered_label:
                continue

            values = []

            for candidate in lines[
                index + 1:
            ]:
                if (
                    candidate.lower()
                    in lowered_stops
                ):
                    break

                values.append(candidate)

            text = "\n".join(
                values
            ).strip()

            return text or None

        return None

    @staticmethod
    def parse_published_at(value):
        if not value:
            return None

        try:
            parsed = datetime.fromisoformat(
                str(value).strip()
            )
        except ValueError:
            return None

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.astimezone(
            timezone.utc
        )

    @classmethod
    def normalize_employment_type(
        cls,
        value,
    ):
        normalized = cls.normalize_space(
            value
        ).lower()

        mapping = {
            "full time": "Full-time",
            "full-time": "Full-time",
            "part time": "Part-time",
            "part-time": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "intern": "Internship",
            "internship": "Internship",
            "temporary": "Temporary",
        }

        return (
            mapping.get(normalized)
            or (
                cls.normalize_space(
                    value
                )
                if value
                else None
            )
        )

    @classmethod
    def normalize_experience_level(
        cls,
        value,
    ):
        normalized = cls.normalize_space(
            value
        ).lower()

        mapping = {
            "intern": "intern",
            "entry": "entry",
            "junior": "junior",
            "mid": "mid",
            "senior": "senior",
            "staff": "staff",
            "principal": "principal",
            "lead": "lead",
            "manager": "manager",
        }

        return mapping.get(
            normalized
        )

    @classmethod
    def detect_workplace_type(
        cls,
        location,
    ):
        lowered = cls.normalize_space(
            location
        ).lower()

        if not lowered:
            return None

        if "hybrid" in lowered:
            return "Hybrid"

        if "remote" in lowered:
            return "Remote"

        return "On-site"

    @classmethod
    def detect_visa_sponsorship(
        cls,
        description,
    ):
        lowered = str(
            description or ""
        ).lower()

        if re.search(
            r"\bno visa sponsorship\b|"
            r"\bvisa sponsorship (?:is )?not available\b|"
            r"\bcannot sponsor\b|"
            r"\bunable to sponsor\b",
            lowered,
        ):
            return "No"

        if re.search(
            r"\bvisa sponsorship available\b|"
            r"\bcan sponsor\b|"
            r"\bsponsor(?:s|ing)? (?:a )?work permit\b|"
            r"\bsponsorship provided\b",
            lowered,
        ):
            return "Yes"

        return "Unknown"

    @classmethod
    def find_apply_url(
        cls,
        detail_root,
        posting_url,
    ):
        apply_element = detail_root.find(
            attrs={
                "data-apply-url": True,
            }
        )

        if apply_element is not None:
            href = cls.normalize_space(
                apply_element.get(
                    "data-apply-url"
                )
            )

            if (
                href
                and href.lower()
                not in {
                    "none",
                    "null",
                }
                and not href.startswith("#")
                and not href.lower().startswith(
                    "javascript:"
                )
            ):
                return urljoin(
                    cls.base_url,
                    href,
                )

        for anchor in detail_root.find_all(
            "a",
            href=True,
        ):
            text = cls.normalize_space(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            ).lower()

            if text != "apply":
                continue

            href = cls.normalize_space(
                anchor.get("href")
            )

            if (
                not href
                or href.startswith("#")
                or href.lower().startswith(
                    "javascript:"
                )
            ):
                continue

            return urljoin(
                cls.base_url,
                href,
            )

        return posting_url

    @classmethod
    def normalize_salary(
        cls,
        header_lines,
    ):
        if len(header_lines) <= 3:
            return None

        value = cls.normalize_space(
            " ".join(
                header_lines[3:]
            )
        )

        if not value:
            return None

        if value.lower() == "not provided":
            return None

        value = re.sub(
            r"\s+-\s+",
            " - ",
            value,
        )

        return value

    @classmethod
    def parse_job_page(
        cls,
        job_id,
    ):
        posting_url = cls.detail_url(
            job_id
        )
        html = fetch_html(
            cls.detail_section_url(
                job_id
            ),
            timeout=30,
        )
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        detail_root = cls.find_detail_root(
            soup
        )
        lines = cls.normalized_lines(
            detail_root
        )
        published_index = (
            cls.find_published_index(
                lines
            )
        )

        if published_index is None:
            return None

        (
            company,
            title,
        ) = cls.extract_company_title(
            detail_root,
            lines,
            published_index,
        )

        published_at = (
            cls.parse_published_at(
                lines[
                    published_index + 1
                ]
            )
        )
        employment_type = (
            cls.normalize_employment_type(
                cls.extract_labeled_value(
                    lines,
                    "Job type",
                )
            )
        )
        workplace_value = (
            cls.extract_labeled_value(
                lines,
                "Workplace",
            )
        )
        location = (
            cls.extract_labeled_value(
                lines,
                "Location",
            )
        )
        seniority = (
            cls.normalize_experience_level(
                cls.extract_labeled_value(
                    lines,
                    "Seniority level",
                )
            )
        )
        timezone_value = (
            cls.extract_labeled_value(
                lines,
                "Timezone",
            )
        )

        description = cls.extract_section(
            lines,
            "Job description",
            (
                "Required skills",
                "Apply instructions",
                "About company",
                "Share this job",
                "Close modal",
            ),
        )

        required_skills = (
            cls.extract_section(
                lines,
                "Required skills",
                (
                    "Apply instructions",
                    "About company",
                    "Share this job",
                    "Close modal",
                ),
            )
        )

        description_parts = []

        if description:
            description_parts.append(
                description
            )

        if required_skills:
            description_parts.append(
                "Required skills\n"
                f"{required_skills}"
            )

        if timezone_value:
            description_parts.append(
                "Timezone\n"
                f"{timezone_value}"
            )

        job_description = (
            "\n\n".join(
                description_parts
            )
            or None
        )

        workplace_type = (
            cls.detect_workplace_type(
                " ".join(
                    value
                    for value in (
                        workplace_value,
                        location,
                    )
                    if value
                )
            )
        )

        return {
            "source": cls.source_name,
            "external_id": job_id,
            "company_name": (
                company
                or "Unknown Company"
            ),
            "position_title": (
                title
                or "Untitled Position"
            ),
            "location": location,
            "employment_type": (
                employment_type
            ),
            "salary": (
                cls.extract_salary(
                    lines
                )
            ),
            "visa_sponsorship": (
                cls.detect_visa_sponsorship(
                    job_description
                )
            ),
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": (
                cls.find_apply_url(
                    detail_root,
                    posting_url,
                )
            ),
            "job_description": (
                job_description
            ),
            "departments": [],
            "offices": (
                [location]
                if location
                else []
            ),
            "is_remote": (
                workplace_type == "Remote"
            ),
            "workplace_type": (
                workplace_type
            ),
            "remote_candidate_scope": None,
            "remote_allowed_locations": [],
            "published_at": published_at,
            "experience_level": seniority,
            "seniority_level": seniority,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_jobs(cls):
        job_ids = cls.discover_job_ids()

        if not job_ids:
            raise RuntimeError(
                "CNCF GitJobs returned no discoverable job IDs."
            )

        jobs = []
        failures = 0

        with ThreadPoolExecutor(
            max_workers=cls.max_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.parse_job_page,
                    job_id,
                ): job_id
                for job_id in job_ids
            }

            for future in as_completed(
                future_map
            ):
                job_id = future_map[
                    future
                ]

                try:
                    job = future.result()

                    if job:
                        jobs.append(job)
                    else:
                        failures += 1
                        print(
                            "CNCF GITJOBS PARSE SKIP | "
                            f"Job ID: {job_id}"
                        )

                except Exception as error:
                    failures += 1
                    print(
                        "CNCF GITJOBS PAGE FAILED | "
                        f"Job ID: {job_id} | "
                        f"Error: {error}"
                    )

        deduplicated = {
            job["external_id"]: job
            for job in jobs
            if job.get(
                "external_id"
            )
        }

        prepared_jobs = list(
            deduplicated.values()
        )

        stats = {
            "discovered": len(job_ids),
            "parsed": len(jobs),
            "failed": failures,
            "unique": len(
                prepared_jobs
            ),
        }

        print(
            "CNCF GITJOBS FEED | "
            f"Discovered: {stats['discovered']} | "
            f"Parsed: {stats['parsed']} | "
            f"Failed: {stats['failed']} | "
            f"Unique: {stats['unique']}"
        )

        return prepared_jobs, stats

    def prepare(
        self,
        profiles,
    ):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "CNCF GITJOBS CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        jobs, stats = self.fetch_jobs()

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

        with collect_match_diagnostics() as diagnostics:
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
            "CNCF GITJOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        if (
            diagnostics["evaluated"] > 0
            and diagnostics["matched"] > 0
        ):
            print(
                format_match_diagnostics(
                    profile.name,
                    self.source_name,
                    diagnostics,
                )
            )

        return matching_jobs
