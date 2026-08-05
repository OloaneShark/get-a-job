
import hashlib
import os
import re
import sys
import threading
import xml.etree.ElementTree as ET

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from email.utils import parsedate_to_datetime
from types import SimpleNamespace
from urllib.parse import urlparse

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_response,
)
from services.job_sources.job_match_service import (
    job_matches_profile,
)
from services.job_sources.we_work_remotely_crawler import (
    crawl_recent_wwr_jobs,
)


def environment_flag(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def source_debug_enabled():
    return environment_flag(
        "JOB_SOURCE_DEBUG",
        default=False,
    )


def safe_terminal_text(value):
    text = str(value or "")
    encoding = (
        getattr(sys.stdout, "encoding", None)
        or "utf-8"
    )

    return text.encode(
        encoding,
        errors="backslashreplace",
    ).decode(
        encoding,
        errors="replace",
    )


def safe_print(message):
    print(safe_terminal_text(message))


class WeWorkRemotelyJobSource(BaseJobSource):
    source_name = "We Work Remotely"
    source_type = "we_work_remotely"
    requires_company_config = False

    feed_url = (
        "https://weworkremotely.com/"
        "remote-jobs.rss"
    )

    max_job_age_days = 30

    # Fetch and normalize one union feed for all active
    # profiles, then apply the shared matcher per profile.
    cache_duration = timedelta(hours=1)
    pages_per_profile = 20
    maximum_shared_pages = 100

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cache_signature = None
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
    def parse_profile_values(value):
        if not value:
            return []

        return [
            item.strip().lower()
            for item in re.split(
                r"[\n,]+",
                str(value),
            )
            if item.strip()
        ]

    @classmethod
    def build_discovery_profile(cls, profiles):
        profiles = [
            profile
            for profile in profiles
            if profile is not None
        ]

        keywords = set()
        experience_levels = set()

        for profile in profiles:
            keywords.update(
                cls.parse_profile_values(
                    getattr(
                        profile,
                        "keywords",
                        None,
                    )
                )
            )
            experience_levels.update(
                cls.parse_profile_values(
                    getattr(
                        profile,
                        "experience_levels",
                        None,
                    )
                )
            )

        profile_count = max(
            1,
            len(profiles),
        )
        max_job_pages = min(
            cls.maximum_shared_pages,
            cls.pages_per_profile
            * profile_count,
        )

        signature = (
            tuple(sorted(keywords)),
            tuple(sorted(experience_levels)),
            max_job_pages,
        )

        discovery_profile = SimpleNamespace(
            name="Shared active profiles",
            keywords=",".join(
                sorted(keywords)
            ),
            experience_levels=",".join(
                sorted(experience_levels)
            ),
        )

        return (
            discovery_profile,
            signature,
            max_job_pages,
        )

    @staticmethod
    def local_tag_name(tag):
        return tag.split("}")[-1].lower()

    @staticmethod
    def parse_datetime(value):
        if not value:
            return None

        text = str(value).strip()

        if not text:
            return None

        try:
            parsed_value = (
                parsedate_to_datetime(
                    text
                )
            )
        except (TypeError, ValueError):
            parsed_value = None

        if parsed_value is None:
            normalized_text = text

            if normalized_text.endswith("Z"):
                normalized_text = (
                    normalized_text[:-1]
                    + "+00:00"
                )

            try:
                parsed_value = (
                    datetime.fromisoformat(
                        normalized_text
                    )
                )
            except ValueError:
                return None

        if parsed_value.tzinfo is None:
            parsed_value = (
                parsed_value.replace(
                    tzinfo=timezone.utc
                )
            )

        return parsed_value.astimezone(
            timezone.utc
        )

    @classmethod
    def is_recent(cls, value):
        published_at = cls.parse_datetime(
            value
        )

        if published_at is None:
            return False

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(
                days=cls.max_job_age_days
            )
        )

        return published_at >= cutoff

    @staticmethod
    def split_company_and_title(value):
        text = (
            clean_html_text(value)
            or ""
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if not text:
            return (
                "Unknown Company",
                "Untitled Position",
            )

        # WWR commonly formats RSS titles as:
        # Company Name: Position Title
        if ":" in text:
            (
                company_name,
                position_title,
            ) = text.split(
                ":",
                1,
            )

            company_name = (
                company_name.strip()
            )
            position_title = (
                position_title.strip()
            )

            if (
                company_name
                and position_title
            ):
                return (
                    company_name,
                    position_title,
                )

        return (
            "Unknown Company",
            text,
        )

    @staticmethod
    def create_external_id(
        guid,
        posting_url,
    ):
        guid_text = str(
            guid or ""
        ).strip()

        if guid_text:
            return guid_text

        parsed_url = urlparse(
            posting_url or ""
        )
        slug = (
            parsed_url.path
            .strip("/")
            .split("/")[-1]
        )

        if slug:
            return slug

        fingerprint_source = str(
            posting_url or ""
        ).strip()

        if not fingerprint_source:
            return None

        return hashlib.sha256(
            fingerprint_source.encode(
                "utf-8"
            )
        ).hexdigest()[:24]

    @staticmethod
    def normalize_location(value):
        location = clean_html_text(
            value
        )

        if not location:
            return "Remote"

        location = re.sub(
            r"\s+",
            " ",
            location,
        ).strip()

        replacements = {
            "anywhere in the world": (
                "Worldwide"
            ),
            "anywhere": "Worldwide",
            "worldwide": "Worldwide",
        }

        return replacements.get(
            location.lower(),
            location,
        )

    @staticmethod
    def normalize_employment_type(value):
        text = clean_html_text(
            value
        )

        if not text:
            return None

        mappings = {
            "full-time": "Full-time",
            "full time": "Full-time",
            "full_time": "Full-time",
            "part-time": "Part-time",
            "part time": "Part-time",
            "part_time": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "temporary": "Temporary",
            "internship": "Internship",
            "intern": "Internship",
        }

        return mappings.get(
            text.lower(),
            text,
        )

    @staticmethod
    def extract_item_fields(item):
        fields = {}

        for child in item:
            field_name = (
                WeWorkRemotelyJobSource
                .local_tag_name(child.tag)
            )
            field_value = str(
                child.text or ""
            ).strip()

            if not field_value:
                continue

            if field_name not in fields:
                fields[field_name] = (
                    field_value
                )

        return fields

    @staticmethod
    def deduplicate_jobs(jobs):
        deduplicated = {}

        for job in jobs:
            posting_url = str(
                job.get("posting_url")
                or ""
            ).strip().rstrip("/")
            external_id = str(
                job.get("external_id")
                or ""
            ).strip()
            deduplication_key = (
                posting_url
                or external_id
            )

            if not deduplication_key:
                continue

            deduplicated[
                deduplication_key
            ] = job

        return list(
            deduplicated.values()
        )

    def fetch_jobs(self):
        response = fetch_response(
            self.feed_url,
            headers={
                "Accept": (
                    "application/rss+xml, "
                    "application/xml, "
                    "text/xml"
                )
            },
            timeout=60,
        )

        try:
            root = ET.fromstring(
                response.content
            )
        except ET.ParseError as error:
            raise RuntimeError(
                "We Work Remotely RSS feed "
                f"could not be parsed: {error}"
            ) from error

        raw_jobs = []

        for element in root.iter():
            if (
                self.local_tag_name(
                    element.tag
                )
                != "item"
            ):
                continue

            fields = self.extract_item_fields(
                element
            )

            if fields:
                raw_jobs.append(fields)

        print(
            "WWR FEED: fetched "
            f"{len(raw_jobs)} RSS entries."
        )

        return raw_jobs

    def normalize_job(self, raw_job):
        (
            company_name,
            position_title,
        ) = self.split_company_and_title(
            raw_job.get("title")
        )

        posting_url = (
            raw_job.get("link")
            or raw_job.get("guid")
        )
        published_value = (
            raw_job.get("pubdate")
            or raw_job.get("published")
            or raw_job.get("date")
        )
        published_at = (
            self.parse_datetime(
                published_value
            )
        )
        description = clean_html_text(
            raw_job.get("description")
            or raw_job.get("content")
            or raw_job.get("encoded")
        )
        location = self.normalize_location(
            raw_job.get("region")
            or raw_job.get("location")
        )
        employment_type = (
            self.normalize_employment_type(
                raw_job.get(
                    "employment_type"
                )
                or raw_job.get(
                    "employmenttype"
                )
                or raw_job.get("type")
            )
        )
        category = clean_html_text(
            raw_job.get("category")
        )
        departments = []

        if category:
            departments.append(category)

        return {
            "source": self.source_name,
            "external_id": (
                self.create_external_id(
                    raw_job.get("guid"),
                    posting_url,
                )
            ),
            "company_name": company_name,
            "position_title": (
                position_title
            ),
            "location": location,
            "employment_type": (
                employment_type
                or "Full-time"
            ),
            "salary": None,
            "visa_sponsorship": "unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": departments,
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": published_at,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @staticmethod
    def is_plausible_job(job):
        title = str(
            job.get("position_title")
            or ""
        ).strip()
        company = str(
            job.get("company_name")
            or ""
        ).strip()
        posting_url = str(
            job.get("posting_url")
            or ""
        ).strip()

        if not title:
            return False

        if not company:
            return False

        if not posting_url:
            return False

        if title == "Untitled Position":
            return False

        rejected_titles = {
            "join our team",
            "join us",
            "current vacancies",
            "open positions",
            "job title",
        }

        if title.lower() in rejected_titles:
            return False

        return True

    def prepare(self, profiles):
        (
            discovery_profile,
            signature,
            max_job_pages,
        ) = self.build_discovery_profile(
            profiles
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
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "WWR CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "shared normalized jobs."
                )
                return list(
                    self._prepared_jobs
                )

            raw_jobs = self.fetch_jobs()
            rss_jobs = []
            old_count = 0
            invalid_count = 0

            for raw_job in raw_jobs:
                published_value = (
                    raw_job.get("pubdate")
                    or raw_job.get(
                        "published"
                    )
                    or raw_job.get("date")
                )

                if not self.is_recent(
                    published_value
                ):
                    old_count += 1
                    continue

                job = self.normalize_job(
                    raw_job
                )

                if not self.is_plausible_job(
                    job
                ):
                    invalid_count += 1

                    if source_debug_enabled():
                        safe_print(
                            "WWR INVALID RECORD | "
                            f"Title: "
                            f"{job.get('position_title')} | "
                            f"Company: "
                            f"{job.get('company_name')}"
                        )

                    continue

                rss_jobs.append(job)

            rss_urls = {
                str(
                    job.get("posting_url")
                    or ""
                ).strip().rstrip("/")
                for job in rss_jobs
                if job.get("posting_url")
            }

            # Crawl once for the union of every active
            # profile's role and experience preferences.
            crawled_jobs = (
                crawl_recent_wwr_jobs(
                    profile=discovery_profile,
                    excluded_urls=rss_urls,
                    max_age_days=30,
                    max_job_pages=max_job_pages,
                )
            )

            combined_jobs = (
                self.deduplicate_jobs(
                    rss_jobs
                    + crawled_jobs
                )
            )
            prepared_jobs = [
                job
                for job in combined_jobs
                if self.is_plausible_job(job)
            ]
            stats = {
                "feed_count": len(raw_jobs),
                "rss_count": len(rss_jobs),
                "crawled_count": (
                    len(crawled_jobs)
                ),
                "old_count": old_count,
                "invalid_count": (
                    invalid_count
                ),
                "max_job_pages": (
                    max_job_pages
                ),
            }

            source_class._cached_jobs = list(
                prepared_jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(timezone.utc)
            )
            source_class._cache_signature = (
                signature
            )
            source_class._cached_stats = dict(
                stats
            )

            self._prepared_jobs = list(
                prepared_jobs
            )
            self._prepared_stats = dict(
                stats
            )

            print(
                "WWR SHARED FEED | "
                f"Profiles combined: "
                f"{max(1, len(profiles))} | "
                f"Feed: {len(raw_jobs)} | "
                f"Recent RSS: "
                f"{len(rss_jobs)} | "
                f"Crawled: "
                f"{len(crawled_jobs)} | "
                f"Combined valid: "
                f"{len(prepared_jobs)} | "
                f"Older than "
                f"{self.max_job_age_days} "
                f"days: {old_count} | "
                f"Invalid: "
                f"{invalid_count} | "
                f"Page limit: "
                f"{max_job_pages}"
            )

            return list(
                prepared_jobs
            )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if self._prepared_jobs is None:
            self.prepare([profile])

        all_jobs = list(
            self._prepared_jobs
            or []
        )
        stats = dict(
            self._prepared_stats
            or {}
        )
        matching_jobs = []

        print(
            "WWR SEARCH | "
            f"Profile: {profile.name} | "
            f"Shared feed: "
            f"{len(all_jobs)} | "
            f"Feed: "
            f"{stats.get('feed_count', 0)} | "
            f"Recent RSS: "
            f"{stats.get('rss_count', 0)} | "
            f"Crawled: "
            f"{stats.get('crawled_count', 0)}"
        )

        for job in all_jobs:
            if not job_matches_profile(
                job,
                profile,
            ):
                continue

            matching_jobs.append(job)

        print(
            "WWR SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: "
            f"{len(matching_jobs)}"
        )

        return matching_jobs
