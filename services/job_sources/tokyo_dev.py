
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_html
from services.job_sources.job_match_service import (
    collect_match_diagnostics,
    format_match_diagnostics,
    job_matches_profile,
)


class TokyoDevJobSource(BaseJobSource):
    source_name = "TokyoDev"
    source_type = "tokyo_dev"
    requires_company_config = False

    base_url = "https://www.tokyodev.com"
    jobs_url = f"{base_url}/jobs"
    cache_duration = timedelta(hours=6)
    max_workers = 4

    _cached_jobs = None
    _cache_fetched_at = None
    _cache_lock = threading.Lock()

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
        return re.sub(r"\s+", " ", str(value or "")).strip()

    @classmethod
    def discover_job_urls(cls):
        html = fetch_html(cls.jobs_url)
        paths = re.findall(
            r'href=["\\\']([^"\\\']*?/companies/'
            r'[^"\\\']+/jobs/[^"\\\']+)["\\\']',
            html,
            flags=re.IGNORECASE,
        )

        urls = []
        seen = set()

        for path in paths:
            absolute_url = urljoin(cls.base_url, path)
            parsed = urlparse(absolute_url)

            if parsed.netloc != "www.tokyodev.com":
                continue

            clean_url = (
                f"{parsed.scheme}://{parsed.netloc}"
                f"{parsed.path}"
            )

            if clean_url not in seen:
                seen.add(clean_url)
                urls.append(clean_url)

        print(
            "TOKYODEV LISTING DISCOVERY | "
            f"Unique job URLs: {len(urls)}"
        )

        return urls

    @staticmethod
    def find_job_posting_json(soup):
        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"},
        ):
            raw_value = script.string or script.get_text()

            if not raw_value:
                continue

            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError):
                continue

            candidates = payload if isinstance(payload, list) else [payload]

            for candidate in candidates:
                if (
                    isinstance(candidate, dict)
                    and candidate.get("@type") == "JobPosting"
                ):
                    return candidate

        return None

    @staticmethod
    def extract_page_text(soup):
        main = soup.find("main") or soup.find("article") or soup.body

        if main is None:
            return ""

        return re.sub(
            r"\n{3,}",
            "\n\n",
            main.get_text("\n", strip=True),
        )

    @classmethod
    def normalize_location(cls, job_posting):
        raw_locations = job_posting.get("jobLocation")
        locations = (
            raw_locations
            if isinstance(raw_locations, list)
            else [raw_locations]
        )

        parts = []

        for item in locations:
            if not isinstance(item, dict):
                continue

            address = item.get("address") or {}

            if not isinstance(address, dict):
                continue

            for key in (
                "addressLocality",
                "addressRegion",
                "addressCountry",
            ):
                value = cls.normalize_space(address.get(key))

                if value and value not in parts:
                    parts.append(value)

        if not parts:
            return "Japan"

        return ", ".join(
            "Japan" if part == "JP" else part
            for part in parts
        )

    @classmethod
    def normalize_employment_type(cls, value):
        mapping = {
            "FULL_TIME": "Full-time",
            "PART_TIME": "Part-time",
            "CONTRACTOR": "Contract",
            "TEMPORARY": "Temporary",
            "INTERN": "Internship",
            "OTHER": "Other",
        }

        normalized = cls.normalize_space(value)

        return mapping.get(
            normalized,
            normalized.replace("_", " ").title()
            if normalized
            else None,
        )

    @classmethod
    def format_salary(cls, base_salary):
        if not isinstance(base_salary, dict):
            return None

        currency = cls.normalize_space(
            base_salary.get("currency")
        ) or "JPY"

        value = base_salary.get("value") or {}

        if not isinstance(value, dict):
            return None

        minimum = value.get("minValue")
        maximum = value.get("maxValue")
        unit = cls.normalize_space(
            value.get("unitText")
        ).lower()

        suffix = {
            "year": "per year",
            "month": "per month",
            "hour": "per hour",
        }.get(unit, unit or "")

        if minimum is not None and maximum is not None:
            return (
                f"{currency} {minimum:,.0f} - "
                f"{maximum:,.0f} {suffix}"
            ).strip()

        if minimum is not None:
            return (
                f"From {currency} {minimum:,.0f} "
                f"{suffix}"
            ).strip()

        if maximum is not None:
            return (
                f"Up to {currency} {maximum:,.0f} "
                f"{suffix}"
            ).strip()

        return None

    @staticmethod
    def detect_workplace_type(page_text):
        lowered = page_text.lower()

        if any(
            phrase in lowered
            for phrase in (
                "partially remote",
                "partial remote",
                "hybrid",
            )
        ):
            return "Hybrid", True

        if any(
            phrase in lowered
            for phrase in (
                "fully remote",
                "100% remote",
                "remote from anywhere",
                "work remotely from anywhere",
            )
        ):
            return "Remote", True

        return "On-site", False

    @staticmethod
    def detect_overseas_status(page_text):
        lowered = page_text.lower()

        if any(
            phrase in lowered
            for phrase in (
                "japan residents only",
                "only open to current residents of japan",
                "only open to residents of japan",
                "current residents of japan only",
                "residency in japan required",
            )
        ):
            return "No"

        if any(
            phrase in lowered
            for phrase in (
                "apply from abroad",
                "overseas applicants welcome",
                "open to overseas applicants",
                "applications from overseas",
                "you can apply from overseas",
            )
        ):
            return "Yes"

        return "Unknown"

    @staticmethod
    def detect_visa_sponsorship(page_text):
        lowered = page_text.lower()

        if any(
            phrase in lowered
            for phrase in (
                "no visa sponsorship",
                "visa sponsorship is not available",
                "cannot sponsor visas",
            )
        ):
            return "No"

        if any(
            phrase in lowered
            for phrase in (
                "visa sponsorship available",
                "visa sponsorship provided",
                "sponsor your visa",
                "visa support available",
            )
        ):
            return "Yes"

        return "Unknown"

    @staticmethod
    def detect_remote_scope(workplace_type, page_text):
        if workplace_type != "Remote":
            return None, []

        lowered = page_text.lower()

        if any(
            phrase in lowered
            for phrase in (
                "remote from anywhere",
                "work remotely from anywhere",
                "worldwide remote",
            )
        ):
            return "worldwide", []

        return "selected_locations", ["Japan"]

    @classmethod
    def find_apply_url(cls, soup, posting_url):
        for anchor in soup.find_all("a", href=True):
            text = cls.normalize_space(
                anchor.get_text(" ", strip=True)
            ).lower()
            href = anchor.get("href") or ""

            if (
                "continue applying" in text
                or "/applications/new" in href
            ):
                return urljoin(cls.base_url, href)

        return posting_url

    @classmethod
    def parse_job_page(cls, posting_url):
        soup = BeautifulSoup(
            fetch_html(posting_url),
            "html.parser",
        )

        job_posting = cls.find_job_posting_json(soup)

        if not job_posting:
            return None

        page_text = cls.extract_page_text(soup)
        workplace_type, is_remote = cls.detect_workplace_type(
            page_text
        )
        remote_scope, remote_locations = cls.detect_remote_scope(
            workplace_type,
            page_text,
        )

        organization = job_posting.get("hiringOrganization") or {}
        company_name = (
            organization.get("name")
            if isinstance(organization, dict)
            else None
        )

        overseas_status = cls.detect_overseas_status(page_text)
        visa_sponsorship = cls.detect_visa_sponsorship(page_text)
        description = clean_html_text(
            job_posting.get("description")
        )

        metadata = (
            "Job conditions\n"
            f"Overseas applicants: {overseas_status}\n"
            f"Visa sponsorship: {visa_sponsorship}\n"
            f"Workplace type: {workplace_type}"
        )

        parsed = urlparse(posting_url)

        return {
            "source": cls.source_name,
            "external_id": parsed.path.strip("/"),
            "company_name": company_name or "Unknown Company",
            "position_title": (
                job_posting.get("title")
                or "Untitled Position"
            ),
            "location": cls.normalize_location(job_posting),
            "employment_type": cls.normalize_employment_type(
                job_posting.get("employmentType")
            ),
            "salary": cls.format_salary(
                job_posting.get("baseSalary")
            ),
            "visa_sponsorship": visa_sponsorship,
            "overseas_applicant_status": overseas_status,
            "posting_url": posting_url,
            "apply_url": cls.find_apply_url(
                soup,
                posting_url,
            ),
            "job_description": "\n\n".join(
                value
                for value in (
                    description,
                    metadata,
                )
                if value
            ) or None,
            "departments": [],
            "offices": [],
            "is_remote": is_remote,
            "workplace_type": workplace_type,
            "remote_candidate_scope": remote_scope,
            "remote_allowed_locations": remote_locations,
            "published_at": job_posting.get("datePosted"),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_jobs(cls):
        urls = cls.discover_job_urls()
        jobs = []
        completed = 0

        with ThreadPoolExecutor(
            max_workers=cls.max_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.parse_job_page,
                    url,
                ): url
                for url in urls
            }

            for future in as_completed(future_map):
                completed += 1
                url = future_map[future]

                try:
                    job = future.result()

                    if job:
                        jobs.append(job)

                except Exception as error:
                    print(
                        "TOKYODEV JOB PAGE FAILED | "
                        f"URL: {url} | "
                        f"Error: {error}"
                    )

                if (
                    completed % 20 == 0
                    or completed == len(urls)
                ):
                    print(
                        "TOKYODEV CRAWL PROGRESS | "
                        f"{completed}/{len(urls)} "
                        "pages processed."
                    )

        return jobs

    def get_cached_jobs(self):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                print(
                    "TOKYODEV CACHE | "
                    f"Using {len(source_class._cached_jobs)} "
                    "cached jobs."
                )
                return list(source_class._cached_jobs)

            jobs = source_class.fetch_jobs()
            source_class._cached_jobs = jobs
            source_class._cache_fetched_at = (
                datetime.now(timezone.utc)
            )

            print(
                "TOKYODEV FEED | "
                f"Fetched {len(jobs)} jobs."
            )

            return list(jobs)

    def search(self, profile, source_config=None):
        jobs = self.get_cached_jobs()

        with collect_match_diagnostics() as diagnostics:
            matching_jobs = [
                job
                for job in jobs
                if job_matches_profile(
                    job,
                    profile,
                )
            ]

        print(
            "TOKYODEV SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        print(
            format_match_diagnostics(
                profile.name,
                self.source_name,
                diagnostics,
            )
        )

        return matching_jobs
