
import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from services.job_sources.http_client import (
    fetch_json,
    post_json,
)


class WorkdayCrawler:
    """
    Handles Workday-specific network operations.

    Responsibilities:
    - Parse Workday career-board URLs.
    - Fetch paginated Workday job listings.
    - Fetch individual Workday job details.
    - Cache listing and detail responses.
    - Return source-level Workday data.

    Profile matching and Job Ad Infinitum-specific
    normalization belong in workday.py.
    """

    page_size = 20
    max_listing_jobs = 2000

    listing_cache_duration = timedelta(minutes=15)
    detail_cache_duration = timedelta(minutes=30)

    _listing_cache = {}
    _detail_cache = {}
    _cache_lock = threading.Lock()

    WORKDAY_HOST_PATTERN = re.compile(
        r"^(?P<tenant>[^.]+)\."
        r"(?P<region>wd\d+)\."
        r"myworkdayjobs\.com$",
        re.IGNORECASE,
    )

    WORKDAY_LOCALE_PATTERN = re.compile(
        r"^[a-z]{2}-[a-z]{2}$",
        re.IGNORECASE,
    )

    @classmethod
    def parse_board_url(cls, value):
        """
        Turn a Workday board URL or job-detail URL into
        the pieces needed by Workday's public CXS API.

        Example input:
        https://nvidia.wd5.myworkdayjobs.com/
        en-US/NVIDIAExternalCareerSite/job/example

        Returned site:
        NVIDIAExternalCareerSite
        """

        if not value or not str(value).strip():
            raise ValueError(
                "A Workday careers URL is required."
            )

        cleaned_value = str(value).strip()

        if "://" not in cleaned_value:
            cleaned_value = f"https://{cleaned_value}"

        parsed = urlparse(cleaned_value)
        hostname = (parsed.hostname or "").lower()

        host_match = cls.WORKDAY_HOST_PATTERN.match(
            hostname
        )

        if not host_match:
            raise ValueError(
                "This does not appear to be a "
                "Workday myworkdayjobs URL."
            )

        path_parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        # Workday commonly places a locale before the
        # external career-site name:
        #
        # /en-US/NVIDIAExternalCareerSite
        #
        # Strip the locale when it exists.
        if (
            path_parts
            and cls.WORKDAY_LOCALE_PATTERN.match(
                path_parts[0]
            )
        ):
            path_parts = path_parts[1:]

        if not path_parts:
            raise ValueError(
                "The Workday URL does not contain "
                "an external career-site name."
            )

        site = path_parts[0]

        if site.lower() in {
            "job",
            "jobs",
            "wday",
        }:
            raise ValueError(
                "The Workday URL does not contain "
                "a valid external career-site name."
            )

        tenant = host_match.group("tenant")
        region = host_match.group("region").lower()
        origin = f"https://{hostname}"

        canonical_url = (
            f"{origin}/{site}"
        )

        return {
            "tenant": tenant,
            "region": region,
            "hostname": hostname,
            "origin": origin,
            "site": site,
            "canonical_url": canonical_url,
        }

    @classmethod
    def canonical_board_url(cls, value):
        return cls.parse_board_url(
            value
        )["canonical_url"]

    @staticmethod
    def _cache_is_fresh(
        entry,
        duration,
    ):
        if not entry:
            return False

        fetched_at = entry.get("fetched_at")

        if fetched_at is None:
            return False

        return (
            datetime.now(timezone.utc)
            - fetched_at
        ) < duration

    @staticmethod
    def request_headers(board):
        """
        Headers used by Workday's public careers frontend.
        """

        return {
            "Accept": "application/json",
            "Accept-Language": "en-US",
            "Origin": board["origin"],
            "Referer": (
                f"{board['origin']}/en-US/"
                f"{board['site']}"
            ),
        }

    @staticmethod
    def jobs_api_url(board):
        return (
            f"{board['origin']}/wday/cxs/"
            f"{board['tenant']}/"
            f"{board['site']}/jobs"
        )

    @staticmethod
    def public_job_url(
        board,
        external_path,
    ):
        path = str(
            external_path or ""
        ).strip()

        if not path:
            return None

        if not path.startswith("/"):
            path = f"/{path}"

        return (
            f"{board['origin']}/en-US/"
            f"{board['site']}{path}"
        )

    @staticmethod
    def detail_api_url(
        board,
        external_path,
    ):
        path = str(
            external_path or ""
        ).strip()

        if not path:
            raise ValueError(
                "Workday job detail path is missing."
            )

        if not path.startswith("/"):
            path = f"/{path}"

        return (
            f"{board['origin']}/wday/cxs/"
            f"{board['tenant']}/"
            f"{board['site']}{path}"
        )

    @classmethod
    def normalize_listing_job(
        cls,
        board,
        raw_job,
    ):
        """
        Normalize only enough listing data for:
        - validation
        - role pre-filtering
        - detail lookup

        Full Job Ad Infinitum normalization happens
        later in workday.py after detail enrichment.
        """

        external_path = str(
            raw_job.get("externalPath")
            or ""
        ).strip()

        posting_url = cls.public_job_url(
            board,
            external_path,
        )

        bullet_fields = (
            raw_job.get("bulletFields")
            or []
        )

        external_id = None

        if isinstance(bullet_fields, list):
            for value in bullet_fields:
                if value:
                    external_id = str(value)
                    break

        title = (
            raw_job.get("title")
            or "Untitled Position"
        )

        return {
            "title": title,
            "position_title": title,
            "posting_url": posting_url,
            "absolute_url": posting_url,
            "externalPath": external_path,
            "external_id": external_id,
            "location": (
                raw_job.get("locationsText")
            ),
            "locationsText": (
                raw_job.get("locationsText")
            ),
            "postedOn": raw_job.get("postedOn"),
            "organization": board["tenant"],
        }

    @classmethod
    def fetch_listings(
        cls,
        board_url,
    ):
        """
        Crawl a Workday career board through its
        paginated public CXS jobs endpoint.
        """

        board = cls.parse_board_url(
            board_url
        )

        cache_key = board["canonical_url"]

        with cls._cache_lock:
            cached = cls._listing_cache.get(
                cache_key
            )

            if cls._cache_is_fresh(
                cached,
                cls.listing_cache_duration,
            ):
                jobs = list(
                    cached["jobs"]
                )

                print(
                    "WORKDAY LISTING CACHE | "
                    f"Board: {board['tenant']}/"
                    f"{board['site']} | "
                    f"Jobs: {len(jobs)}"
                )

                return jobs

        jobs_api_url = cls.jobs_api_url(
            board
        )

        headers = cls.request_headers(
            board
        )

        jobs = []
        seen_paths = set()

        offset = 0
        reported_total = 0

        while offset < cls.max_listing_jobs:
            payload = post_json(
                jobs_api_url,
                json_data={
                    "appliedFacets": {},
                    "limit": cls.page_size,
                    "offset": offset,
                    "searchText": "",
                },
                headers=headers,
                timeout=30,
            )

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Workday returned an unexpected "
                    "listing response."
                )

            if not reported_total:
                try:
                    reported_total = int(
                        payload.get("total", 0)
                        or 0
                    )
                except (
                    TypeError,
                    ValueError,
                ):
                    reported_total = 0

            page_jobs = payload.get(
                "jobPostings",
                [],
            )

            if not isinstance(
                page_jobs,
                list,
            ):
                raise RuntimeError(
                    "Workday returned invalid "
                    "jobPostings data."
                )

            if not page_jobs:
                break

            new_jobs = 0

            for raw_job in page_jobs:
                if not isinstance(
                    raw_job,
                    dict,
                ):
                    continue

                external_path = str(
                    raw_job.get(
                        "externalPath",
                        ""
                    )
                ).strip()

                if (
                    not external_path
                    or external_path
                    in seen_paths
                ):
                    continue

                normalized_job = (
                    cls.normalize_listing_job(
                        board,
                        raw_job,
                    )
                )

                if not normalized_job.get(
                    "posting_url"
                ):
                    continue

                seen_paths.add(
                    external_path
                )

                jobs.append(
                    normalized_job
                )

                new_jobs += 1

            print(
                "WORKDAY LISTING PROGRESS | "
                f"Board: {board['tenant']}/"
                f"{board['site']} | "
                f"Offset: {offset} | "
                f"Collected: {len(jobs)} | "
                f"Reported total: "
                f"{reported_total or 'unknown'}"
            )

            if new_jobs == 0:
                break

            offset += len(page_jobs)

            if (
                reported_total
                and offset >= reported_total
            ):
                break

            if (
                len(page_jobs)
                < cls.page_size
            ):
                break

        with cls._cache_lock:
            cls._listing_cache[
                cache_key
            ] = {
                "fetched_at": datetime.now(
                    timezone.utc
                ),
                "jobs": list(jobs),
            }

        print(
            "WORKDAY LISTING COMPLETE | "
            f"Board: {board['tenant']}/"
            f"{board['site']} | "
            f"Collected: {len(jobs)} | "
            f"Reported total: "
            f"{reported_total or 'unknown'}"
        )

        return jobs

    @classmethod
    def fetch_detail(
        cls,
        board_url,
        external_path,
    ):
        """
        Fetch one Workday job's detailed posting data.
        """

        board = cls.parse_board_url(
            board_url
        )

        cache_key = (
            board["canonical_url"],
            str(external_path),
        )

        with cls._cache_lock:
            cached = cls._detail_cache.get(
                cache_key
            )

            if cls._cache_is_fresh(
                cached,
                cls.detail_cache_duration,
            ):
                return cached["payload"]

        detail_url = cls.detail_api_url(
            board,
            external_path,
        )

        payload = fetch_json(
            detail_url,
            headers=cls.request_headers(
                board
            ),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Workday returned an unexpected "
                "job-detail response."
            )

        with cls._cache_lock:
            cls._detail_cache[
                cache_key
            ] = {
                "fetched_at": datetime.now(
                    timezone.utc
                ),
                "payload": payload,
            }

        return payload
