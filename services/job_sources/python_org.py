import hashlib
import re
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_response,
)
from services.job_sources.job_match_service import (
    job_matches_profile,
)


class PythonOrgJobSource(BaseJobSource):
    source_name = "Python.org"
    source_type = "python_org"
    requires_company_config = False

    feed_url = (
        "https://www.python.org/"
        "jobs/feed/rss/"
    )
    cache_duration = timedelta(hours=1)

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
    def local_tag_name(tag):
        return (
            str(tag or "")
            .split("}")[-1]
            .lower()
        )

    @classmethod
    def extract_item_fields(
        cls,
        item,
    ):
        fields = {}

        for child in item:
            field_name = cls.local_tag_name(
                child.tag
            )

            field_value = "".join(
                child.itertext()
            ).strip()

            if (
                not field_name
                or not field_value
            ):
                continue

            if field_name not in fields:
                fields[
                    field_name
                ] = field_value

        return fields

    @staticmethod
    def parse_datetime(value):
        if not value:
            return None

        text = str(value).strip()

        if not text:
            return None

        try:
            parsed = parsedate_to_datetime(
                text
            )
        except (
            TypeError,
            ValueError,
            OverflowError,
        ):
            parsed = None

        if parsed is None:
            normalized = text

            if normalized.endswith("Z"):
                normalized = (
                    normalized[:-1]
                    + "+00:00"
                )

            try:
                parsed = (
                    datetime.fromisoformat(
                        normalized
                    )
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

    @staticmethod
    def create_external_id(
        guid,
        posting_url,
    ):
        guid = str(
            guid or ""
        ).strip()

        if guid:
            return guid

        value = str(
            posting_url or ""
        ).strip()

        if not value:
            return None

        return hashlib.sha256(
            value.encode("utf-8")
        ).hexdigest()[:24]

    @staticmethod
    def clean_text(value):
        text = clean_html_text(
            value
        )

        if not text:
            return None

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip() or None

    @classmethod
    def extract_labeled_value(
        cls,
        description,
        labels,
    ):
        text = (
            clean_html_text(
                description
            )
            or ""
        )

        for label in labels:
            pattern = re.compile(
                rf"(?:^|\n)\s*"
                rf"{re.escape(label)}"
                r"\s*:\s*"
                r"([^\n]+)",
                re.IGNORECASE,
            )
            match = pattern.search(
                text
            )

            if match:
                value = cls.clean_text(
                    match.group(1)
                )

                if value:
                    return value

        return None

    @classmethod
    def split_title_company(
        cls,
        title,
        explicit_company,
    ):
        title = cls.clean_text(
            title
        ) or "Untitled Position"
        company = cls.clean_text(
            explicit_company
        )

        if company:
            return title, company

        if "," in title:
            role, candidate_company = (
                title.rsplit(",", 1)
            )
            role = cls.clean_text(role)
            candidate_company = (
                cls.clean_text(
                    candidate_company
                )
            )

            if role and candidate_company:
                return (
                    role,
                    candidate_company,
                )

        patterns = (
            r"^(.*?)\s+\bat\b\s+(.+)$",
            r"^(.*?)\s+[–—]\s+(.+)$",
        )

        for pattern in patterns:
            match = re.match(
                pattern,
                title,
                flags=re.IGNORECASE,
            )

            if not match:
                continue

            role = cls.clean_text(
                match.group(1)
            )
            candidate_company = (
                cls.clean_text(
                    match.group(2)
                )
            )

            if role and candidate_company:
                return (
                    role,
                    candidate_company,
                )

        return (
            title,
            "Unknown Company",
        )

    @classmethod
    def normalize_location(
        cls,
        fields,
        description,
    ):
        for field_name in (
            "location",
            "region",
            "joblocation",
            "job_location",
        ):
            value = cls.clean_text(
                fields.get(
                    field_name
                )
            )

            if value:
                return value

        raw_description = str(
            description or ""
        ).strip()

        if raw_description:
            plain_prefix = (
                raw_description
                .split("<", 1)[0]
                .strip()
            )

            if plain_prefix:
                first_line = (
                    plain_prefix
                    .splitlines()[0]
                    .strip()
                )
                first_line = cls.clean_text(
                    first_line
                )

                if (
                    first_line
                    and len(first_line) <= 200
                ):
                    return first_line

        return cls.extract_labeled_value(
            description,
            (
                "Location",
                "Job Location",
            ),
        )

    @classmethod
    def normalize_company(
        cls,
        fields,
        description,
    ):
        for field_name in (
            "company",
            "employer",
            "creator",
            "author",
        ):
            value = cls.clean_text(
                fields.get(
                    field_name
                )
            )

            if value:
                return value

        return cls.extract_labeled_value(
            description,
            (
                "Company",
                "Employer",
            ),
        )

    @staticmethod
    def detect_workplace_type(
        title,
        location,
        description,
    ):
        text = " ".join(
            [
                str(title or ""),
                str(location or ""),
                str(description or ""),
            ]
        ).lower()

        if re.search(
            r"\bhybrid\b",
            text,
        ):
            return "Hybrid"

        if re.search(
            r"\bremote\b|"
            r"\btelecommut(?:e|ing)\b|"
            r"\bwork from home\b|"
            r"\banywhere\b",
            text,
        ):
            return "Remote"

        return None

    @staticmethod
    def normalize_employment_type(
        title,
        description,
    ):
        text = " ".join(
            [
                str(title or ""),
                str(description or ""),
            ]
        ).lower()

        if re.search(
            r"\b(?:intern|internship)\b",
            text,
        ):
            return "Internship"

        if re.search(
            r"\bpart[- ]time\b",
            text,
        ):
            return "Part-time"

        if re.search(
            r"\bcontract(?:or)?\b|"
            r"\b1099\b",
            text,
        ):
            return "Contract"

        if re.search(
            r"\btemporary\b|\btemp\b",
            text,
        ):
            return "Temporary"

        if re.search(
            r"\bfull[- ]time\b",
            text,
        ):
            return "Full-time"

        return None

    @classmethod
    def normalize_job(
        cls,
        fields,
    ):
        if not isinstance(
            fields,
            dict,
        ):
            return None

        posting_url = str(
            fields.get("link")
            or fields.get("guid")
            or ""
        ).strip()

        if not posting_url:
            return None

        raw_description = (
            fields.get(
                "description"
            )
            or fields.get(
                "content"
            )
            or fields.get(
                "encoded"
            )
        )
        description = (
            clean_html_text(
                raw_description
            )
        )

        explicit_company = (
            cls.normalize_company(
                fields,
                description,
            )
        )

        (
            title,
            company,
        ) = cls.split_title_company(
            fields.get("title"),
            explicit_company,
        )

        location = (
            cls.normalize_location(
                fields,
                raw_description,
            )
        )

        workplace_type = (
            cls.detect_workplace_type(
                title,
                location,
                description,
            )
        )

        published_at = (
            cls.parse_datetime(
                fields.get("pubdate")
                or fields.get(
                    "published"
                )
                or fields.get("date")
            )
        )

        categories = []

        for key, value in fields.items():
            if (
                key != "category"
                or not value
            ):
                continue

            cleaned = cls.clean_text(
                value
            )

            if (
                cleaned
                and cleaned
                not in categories
            ):
                categories.append(
                    cleaned
                )

        return {
            "source": cls.source_name,
            "external_id": (
                cls.create_external_id(
                    fields.get("guid"),
                    posting_url,
                )
            ),
            "company_name": company,
            "position_title": title,
            "location": location,
            "employment_type": (
                cls.normalize_employment_type(
                    title,
                    description,
                )
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
            "published_at": (
                published_at
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @staticmethod
    def is_plausible_job(job):
        if not isinstance(
            job,
            dict,
        ):
            return False

        return bool(
            str(
                job.get(
                    "position_title"
                )
                or ""
            ).strip()
            and str(
                job.get(
                    "posting_url"
                )
                or ""
            ).strip()
        )

    @classmethod
    def fetch_jobs(cls):
        response = fetch_response(
            cls.feed_url,
            headers={
                "Accept": (
                    "application/rss+xml, "
                    "application/xml, "
                    "text/xml"
                )
            },
            timeout=30,
        )

        try:
            root = ET.fromstring(
                response.content
            )
        except ET.ParseError as error:
            raise RuntimeError(
                "Python.org jobs RSS feed "
                "could not be parsed: "
                f"{error}"
            ) from error

        raw_jobs = []
        field_names = set()

        for element in root.iter():
            if (
                cls.local_tag_name(
                    element.tag
                )
                != "item"
            ):
                continue

            fields = (
                cls.extract_item_fields(
                    element
                )
            )

            if fields:
                raw_jobs.append(
                    fields
                )
                field_names.update(
                    fields.keys()
                )

        print(
            "PYTHON.ORG FEED | "
            f"Fetched {len(raw_jobs)} "
            "RSS entries."
        )

        if field_names:
            print(
                "PYTHON.ORG FEED SCHEMA | "
                "Fields: "
                f"{sorted(field_names)}"
            )

        return raw_jobs

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
                    "PYTHON.ORG CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )
                return list(
                    self._prepared_jobs
                )

        raw_jobs = self.fetch_jobs()
        normalized_jobs = []
        invalid = 0

        for raw_job in raw_jobs:
            job = self.normalize_job(
                raw_job
            )

            if not self.is_plausible_job(
                job
            ):
                invalid += 1
                continue

            normalized_jobs.append(
                job
            )

        deduplicated = {}

        for job in normalized_jobs:
            key = str(
                job.get(
                    "posting_url"
                )
                or job.get(
                    "external_id"
                )
                or ""
            ).strip().rstrip("/")

            if key:
                deduplicated[
                    key
                ] = job

        prepared_jobs = list(
            deduplicated.values()
        )

        stats = {
            "raw": len(raw_jobs),
            "normalized": (
                len(normalized_jobs)
            ),
            "invalid": invalid,
            "unique": len(
                prepared_jobs
            ),
        }

        with source_class._cache_lock:
            source_class._cached_jobs = list(
                prepared_jobs
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
            prepared_jobs
        )
        self._prepared_stats = dict(
            stats
        )

        remote_count = sum(
            1
            for job in prepared_jobs
            if job.get(
                "workplace_type"
            ) == "Remote"
        )

        known_location_count = sum(
            1
            for job in prepared_jobs
            if job.get("location")
        )

        known_company_count = sum(
            1
            for job in prepared_jobs
            if (
                job.get("company_name")
                and job.get(
                    "company_name"
                )
                != "Unknown Company"
            )
        )

        print(
            "PYTHON.ORG SHARED FEED | "
            f"Raw: {len(raw_jobs)} | "
            f"Normalized: "
            f"{len(normalized_jobs)} | "
            f"Invalid: {invalid} | "
            f"Unique jobs: "
            f"{len(prepared_jobs)} | "
            f"Remote detected: "
            f"{remote_count} | "
            f"Known locations: "
            f"{known_location_count} | "
            f"Known companies: "
            f"{known_company_count}"
        )

        return list(
            self._prepared_jobs
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if not self._prepared_jobs:
            self.prepare(
                [profile]
            )

        matches = [
            job
            for job in self._prepared_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "PYTHON.ORG SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: "
            f"{len(self._prepared_jobs)} | "
            f"Matched: {len(matches)}"
        )

        return matches
