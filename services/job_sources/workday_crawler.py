
import re
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from services.job_sources.http_client import fetch_json, post_json


class WorkdayCrawler:
    page_size = 20
    validation_page_size = 20
    max_jobs_per_search = 120
    listing_cache_duration = timedelta(hours=1)
    detail_cache_duration = timedelta(hours=1)

    _search_cache = {}
    _detail_cache = {}
    _cache_lock = threading.Lock()

    WORKDAY_HOST_PATTERN = re.compile(
        r"^(?P<tenant>[^.]+)\.(?P<region>wd\d+)\.myworkdayjobs\.com$",
        re.IGNORECASE,
    )
    WORKDAY_LOCALE_PATTERN = re.compile(
        r"^[a-z]{2}-[a-z]{2}$",
        re.IGNORECASE,
    )

    @classmethod
    def parse_board_url(cls, value):
        if not value or not str(value).strip():
            raise ValueError("A Workday careers URL is required.")

        cleaned_value = str(value).strip()

        if "://" not in cleaned_value:
            cleaned_value = f"https://{cleaned_value}"

        parsed = urlparse(cleaned_value)
        hostname = (parsed.hostname or "").lower()
        host_match = cls.WORKDAY_HOST_PATTERN.match(hostname)

        if not host_match:
            raise ValueError(
                "This does not appear to be a Workday myworkdayjobs URL."
            )

        path_parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        if (
            path_parts
            and cls.WORKDAY_LOCALE_PATTERN.match(path_parts[0])
        ):
            path_parts = path_parts[1:]

        if not path_parts:
            raise ValueError(
                "The Workday URL does not contain an external career-site name."
            )

        site = path_parts[0]

        if site.lower() in {"job", "jobs", "wday"}:
            raise ValueError(
                "The Workday URL does not contain a valid external career-site name."
            )

        tenant = host_match.group("tenant")
        region = host_match.group("region").lower()
        origin = f"https://{hostname}"

        return {
            "tenant": tenant,
            "region": region,
            "hostname": hostname,
            "origin": origin,
            "site": site,
            "canonical_url": f"{origin}/{site}",
        }

    @classmethod
    def canonical_board_url(cls, value):
        return cls.parse_board_url(value)["canonical_url"]

    @staticmethod
    def _cache_is_fresh(entry, duration):
        if not entry:
            return False

        fetched_at = entry.get("fetched_at")

        if fetched_at is None:
            return False

        return (
            datetime.now(timezone.utc) - fetched_at
        ) < duration

    @staticmethod
    def request_headers(board):
        return {
            "Accept": "application/json",
            "Accept-Language": "en-US",
            "Origin": board["origin"],
            "Referer": (
                f"{board['origin']}/en-US/{board['site']}"
            ),
        }

    @staticmethod
    def jobs_api_url(board):
        return (
            f"{board['origin']}/wday/cxs/"
            f"{board['tenant']}/{board['site']}/jobs"
        )

    @staticmethod
    def public_job_url(board, external_path):
        path = str(external_path or "").strip()

        if not path:
            return None

        if not path.startswith("/"):
            path = f"/{path}"

        return (
            f"{board['origin']}/en-US/"
            f"{board['site']}{path}"
        )

    @staticmethod
    def detail_api_url(board, external_path):
        path = str(external_path or "").strip()

        if not path:
            raise ValueError("Workday job detail path is missing.")

        if not path.startswith("/"):
            path = f"/{path}"

        return (
            f"{board['origin']}/wday/cxs/"
            f"{board['tenant']}/{board['site']}{path}"
        )

    @classmethod
    def normalize_listing_job(cls, board, raw_job):
        external_path = str(
            raw_job.get("externalPath") or ""
        ).strip()

        posting_url = cls.public_job_url(
            board,
            external_path,
        )

        bullet_fields = raw_job.get("bulletFields") or []
        external_id = None

        if isinstance(bullet_fields, list):
            for value in bullet_fields:
                if value:
                    external_id = str(value)
                    break

        title = raw_job.get("title") or "Untitled Position"

        return {
            "title": title,
            "position_title": title,
            "posting_url": posting_url,
            "absolute_url": posting_url,
            "externalPath": external_path,
            "external_id": external_id,
            "location": raw_job.get("locationsText"),
            "locationsText": raw_job.get("locationsText"),
            "postedOn": raw_job.get("postedOn"),
            "organization": board["tenant"],
        }

    @classmethod
    def fetch_validation_listings(cls, board_url):
        board = cls.parse_board_url(board_url)

        payload = post_json(
            cls.jobs_api_url(board),
            json_data={
                "appliedFacets": {},
                "limit": cls.validation_page_size,
                "offset": 0,
                "searchText": "",
            },
            headers=cls.request_headers(board),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Workday returned an unexpected validation response."
            )

        page_jobs = payload.get("jobPostings", [])

        if not isinstance(page_jobs, list):
            raise RuntimeError(
                "Workday returned invalid validation jobPostings data."
            )

        jobs = []

        for raw_job in page_jobs:
            if not isinstance(raw_job, dict):
                continue

            job = cls.normalize_listing_job(
                board,
                raw_job,
            )

            if job.get("posting_url"):
                jobs.append(job)

        print(
            "WORKDAY VALIDATION FETCH | "
            f"Board: {board['tenant']}/{board['site']} | "
            f"Usable sample: {len(jobs)}"
        )

        return jobs

    @classmethod
    def _fetch_search_term(cls, board, search_term):
        normalized_term = re.sub(
            r"\s+",
            " ",
            str(search_term or "").strip().lower(),
        )

        if not normalized_term:
            return [], 0, 0, False

        cache_key = (
            board["canonical_url"],
            normalized_term,
        )

        with cls._cache_lock:
            cached = cls._search_cache.get(cache_key)

            if cls._cache_is_fresh(
                cached,
                cls.listing_cache_duration,
            ):
                return (
                    list(cached["jobs"]),
                    cached["reported_total"],
                    0,
                    True,
                )

        jobs = []
        seen_paths = set()
        offset = 0
        reported_total = 0
        pages = 0

        while offset < cls.max_jobs_per_search:
            remaining = (
                cls.max_jobs_per_search - offset
            )
            limit = min(
                cls.page_size,
                remaining,
            )

            payload = post_json(
                cls.jobs_api_url(board),
                json_data={
                    "appliedFacets": {},
                    "limit": limit,
                    "offset": offset,
                    "searchText": normalized_term,
                },
                headers=cls.request_headers(board),
                timeout=30,
            )

            pages += 1

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Workday returned an unexpected listing response."
                )

            if not reported_total:
                try:
                    reported_total = int(
                        payload.get("total", 0) or 0
                    )
                except (TypeError, ValueError):
                    reported_total = 0

            page_jobs = payload.get("jobPostings", [])

            if not isinstance(page_jobs, list):
                raise RuntimeError(
                    "Workday returned invalid jobPostings data."
                )

            if not page_jobs:
                break

            for raw_job in page_jobs:
                if not isinstance(raw_job, dict):
                    continue

                external_path = str(
                    raw_job.get("externalPath") or ""
                ).strip()

                if (
                    not external_path
                    or external_path in seen_paths
                ):
                    continue

                job = cls.normalize_listing_job(
                    board,
                    raw_job,
                )

                if not job.get("posting_url"):
                    continue

                seen_paths.add(external_path)
                jobs.append(job)

            offset += len(page_jobs)

            if (
                reported_total
                and offset >= reported_total
            ):
                break

            if len(page_jobs) < limit:
                break

        with cls._cache_lock:
            cls._search_cache[cache_key] = {
                "fetched_at": datetime.now(timezone.utc),
                "jobs": list(jobs),
                "reported_total": reported_total,
            }

        return jobs, reported_total, pages, False

    @classmethod
    def fetch_listings(cls, board_url, search_terms):
        board = cls.parse_board_url(board_url)

        normalized_terms = []
        seen_terms = set()

        for term in search_terms or []:
            normalized = re.sub(
                r"\s+",
                " ",
                str(term or "").strip().lower(),
            )

            if (
                normalized
                and normalized not in seen_terms
            ):
                seen_terms.add(normalized)
                normalized_terms.append(normalized)

        if not normalized_terms:
            raise ValueError(
                "Workday targeted search requires at least one search term."
            )

        unique_jobs = {}
        network_pages = 0
        cached_terms = 0

        for term in normalized_terms:
            (
                jobs,
                reported_total,
                pages,
                from_cache,
            ) = cls._fetch_search_term(
                board,
                term,
            )

            network_pages += pages

            if from_cache:
                cached_terms += 1

            for job in jobs:
                external_path = job.get("externalPath")

                if external_path:
                    unique_jobs[external_path] = job

            print(
                "WORKDAY TARGETED SEARCH | "
                f"Board: {board['tenant']}/{board['site']} | "
                f"Query: {term} | "
                f"Returned: {len(jobs)} | "
                f"Reported total: {reported_total or 'unknown'} | "
                f"Cap: {cls.max_jobs_per_search} | "
                f"Cache: {'yes' if from_cache else 'no'}"
            )

        jobs = list(unique_jobs.values())

        print(
            "WORKDAY TARGETED COMPLETE | "
            f"Board: {board['tenant']}/{board['site']} | "
            f"Queries: {len(normalized_terms)} | "
            f"Unique listings: {len(jobs)} | "
            f"Network listing pages: {network_pages} | "
            f"Cached queries: {cached_terms}"
        )

        return jobs

    @classmethod
    def fetch_detail(
        cls,
        board_url,
        external_path,
    ):
        board = cls.parse_board_url(board_url)

        cache_key = (
            board["canonical_url"],
            str(external_path),
        )

        with cls._cache_lock:
            cached = cls._detail_cache.get(cache_key)

            if cls._cache_is_fresh(
                cached,
                cls.detail_cache_duration,
            ):
                return cached["payload"]

        payload = fetch_json(
            cls.detail_api_url(
                board,
                external_path,
            ),
            headers=cls.request_headers(board),
            timeout=30,
        )

        if not isinstance(payload, dict):
            raise RuntimeError(
                "Workday returned an unexpected job-detail response."
            )

        with cls._cache_lock:
            cls._detail_cache[cache_key] = {
                "fetched_at": datetime.now(timezone.utc),
                "payload": payload,
            }

        return payload
    