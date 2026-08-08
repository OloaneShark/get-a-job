
import json
import random
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

from models import (
    JobSourceCandidate,
    JobSourceCompany,
    db,
)
from services.job_sources.discovery.candidate_service import (
    ingest_source_url,
)
from services.job_sources.http_client import fetch_response
from services.job_sources.workday_crawler import WorkdayCrawler


COMMON_CRAWL_COLLECTIONS_URL = (
    "https://index.commoncrawl.org/collinfo.json"
)

MAX_COMMON_CRAWL_INDEXES = 2
COMMON_CRAWL_PAGE_SIZE = 1
PAGES_PER_PATTERN = 4
MAX_RECORDS_PER_PAGE = 500
REQUEST_DELAY_SECONDS = 2.0
MAX_REQUEST_ATTEMPTS = 3
MAX_VALIDATION_ATTEMPTS_PER_SOURCE = 20
TARGET_VALID_BOARDS_PER_SOURCE = 8
INDEX_CACHE_DURATION = timedelta(hours=6)

DISCOVERY_PATTERNS = {
    "lever": (
        "jobs.lever.co/*",
        "jobs.eu.lever.co/*",
    ),
    "greenhouse": (
        "job-boards.greenhouse.io/*",
        "boards.greenhouse.io/*",
    ),
    "ashby": (
        "jobs.ashbyhq.com/*",
    ),
    "workday": (
        "*.myworkdayjobs.com/*",
    ),
}

RESERVED_IDENTIFIERS = {
    "",
    ".well-known",
    "404",
    "about",
    "admin",
    "api",
    "apply",
    "assets",
    "careers",
    "css",
    "demo",
    "example",
    "favicon.ico",
    "favicon.png",
    "feed",
    "health",
    "images",
    "img",
    "index.html",
    "jobs",
    "js",
    "login",
    "manifest.json",
    "privacy",
    "robots.txt",
    "sample",
    "sandbox",
    "search",
    "sitemap",
    "sitemap.xml",
    "static",
    "template",
    "terms",
    "test",
}

IDENTIFIER_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,99}$"
)

FILE_LIKE_SUFFIXES = (
    ".css",
    ".gif",
    ".html",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".webp",
    ".xml",
)

_index_cache = {
    "fetched_at": None,
    "endpoints": [],
}
_page_count_cache = {}


def utc_now():
    return datetime.now(timezone.utc)


def cache_is_fresh(fetched_at):
    return (
        fetched_at is not None
        and (
            utc_now() - fetched_at
        ) < INDEX_CACHE_DURATION
    )


def fetch_with_retries(
    url,
    *,
    params=None,
    timeout=60,
    label="Common Crawl request",
):
    last_error = None

    for attempt in range(
        1,
        MAX_REQUEST_ATTEMPTS + 1,
    ):
        try:
            return fetch_response(
                url,
                params=params,
                timeout=timeout,
            )

        except Exception as error:
            last_error = error
            error_text = str(error)

            print(
                "COMMON CRAWL REQUEST FAILED | "
                f"Label: {label} | "
                f"Attempt: {attempt}/"
                f"{MAX_REQUEST_ATTEMPTS} | "
                f"Error: {error}"
            )

            # Retrying a malformed or missing page will
            # produce the same result and only delays the
            # discovery request. Retry temporary server
            # failures, but stop immediately for 4xx errors.
            permanent_client_error = any(
                status_text in error_text
                for status_text in (
                    "400 Client Error",
                    "404 Client Error",
                )
            )

            if permanent_client_error:
                break

            if attempt < MAX_REQUEST_ATTEMPTS:
                wait_seconds = (
                    REQUEST_DELAY_SECONDS
                    * attempt
                    * 2
                )

                print(
                    "COMMON CRAWL RETRY | "
                    f"Waiting {wait_seconds:.1f} "
                    "seconds."
                )
                time.sleep(wait_seconds)

    raise RuntimeError(
        f"{label} failed after "
        f"{MAX_REQUEST_ATTEMPTS} attempts: "
        f"{last_error}"
    )


def get_common_crawl_indexes(
    maximum_indexes=MAX_COMMON_CRAWL_INDEXES,
):
    if (
        cache_is_fresh(
            _index_cache["fetched_at"]
        )
        and _index_cache["endpoints"]
    ):
        return list(
            _index_cache["endpoints"][
                :maximum_indexes
            ]
        )

    response = fetch_with_retries(
        COMMON_CRAWL_COLLECTIONS_URL,
        timeout=60,
        label="Common Crawl collection listing",
    )

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError(
            "Common Crawl returned an invalid "
            "collection listing."
        ) from error

    if not isinstance(payload, list):
        raise RuntimeError(
            "Common Crawl returned an unexpected "
            "collection listing."
        )

    endpoints = []

    for collection in payload:
        if not isinstance(collection, dict):
            continue

        endpoint = (
            collection.get("cdx-api")
            or collection.get("cdx_api")
        )

        if not endpoint:
            collection_id = (
                collection.get("id")
                or collection.get("name")
            )

            if collection_id:
                endpoint = (
                    "https://index.commoncrawl.org/"
                    f"{collection_id}-index"
                )

        endpoint = str(
            endpoint or ""
        ).strip().rstrip("/")

        if (
            endpoint
            and endpoint not in endpoints
        ):
            endpoints.append(endpoint)

    if not endpoints:
        raise RuntimeError(
            "No usable Common Crawl index "
            "endpoints were returned."
        )

    _index_cache["fetched_at"] = utc_now()
    _index_cache["endpoints"] = endpoints

    selected = endpoints[:maximum_indexes]

    print(
        "AUTOMATIC DISCOVERY INDEXES | "
        f"Using {len(selected)} recent "
        "Common Crawl indexes."
    )

    return list(selected)


def parse_page_count(response_text):
    text = str(
        response_text or ""
    ).strip()

    if not text:
        return 0

    try:
        return max(
            0,
            int(text),
        )
    except ValueError:
        pass

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        number_match = re.search(
            r"\b(\d+)\b",
            text,
        )

        if number_match:
            return int(
                number_match.group(1)
            )

        return 0

    if isinstance(payload, int):
        return max(0, payload)

    if isinstance(payload, dict):
        for key in (
            "pages",
            "numPages",
            "num_pages",
            "pageCount",
            "page_count",
        ):
            value = payload.get(key)

            try:
                return max(
                    0,
                    int(value),
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

    if (
        isinstance(payload, list)
        and payload
    ):
        try:
            return max(
                0,
                int(payload[0]),
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0

    return 0


def fetch_page_count(
    index_endpoint,
    pattern,
):
    cache_key = (
        index_endpoint,
        pattern,
    )
    cached = _page_count_cache.get(
        cache_key
    )

    if (
        cached
        and cache_is_fresh(
            cached["fetched_at"]
        )
    ):
        return cached["page_count"]

    response = fetch_with_retries(
        index_endpoint,
        params={
            "url": pattern,
            "showNumPages": "true",
            "pageSize": (
                COMMON_CRAWL_PAGE_SIZE
            ),
            "filter": "status:200",
            "collapse": "urlkey",
        },
        timeout=60,
        label=(
            "Common Crawl page-count query "
            f"for {pattern}"
        ),
    )
    page_count = parse_page_count(
        response.text
    )

    if page_count <= 0:
        page_count = 1

    _page_count_cache[cache_key] = {
        "fetched_at": utc_now(),
        "page_count": page_count,
    }

    time.sleep(REQUEST_DELAY_SECONDS)
    return page_count


def select_sample_pages(
    page_count,
    pages_to_scan=PAGES_PER_PATTERN,
):
    if page_count <= 1:
        return [0]

    pages_to_scan = max(
        1,
        min(
            int(pages_to_scan),
            page_count,
        ),
    )

    selected = {
        0,
        page_count - 1,
    }

    middle_pages = list(
        range(
            1,
            page_count - 1,
        )
    )
    random.SystemRandom().shuffle(
        middle_pages
    )

    for page in middle_pages:
        if len(selected) >= pages_to_scan:
            break

        selected.add(page)

    return sorted(selected)[
        :pages_to_scan
    ]


def parse_cdx_urls(response_text):
    urls = []

    for line in str(
        response_text or ""
    ).splitlines():
        line = line.strip()

        if not line:
            continue

        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if isinstance(record, str):
            url = record
        elif isinstance(record, dict):
            url = record.get("url")
        else:
            url = None

        url = str(
            url or ""
        ).strip()

        if url:
            urls.append(url)

    return urls


def fetch_common_crawl_page(
    index_endpoint,
    pattern,
    page,
):
    response = fetch_with_retries(
        index_endpoint,
        params={
            "url": pattern,
            "output": "json",
            "fl": "url",
            "filter": "status:200",
            "collapse": "urlkey",
            "pageSize": (
                COMMON_CRAWL_PAGE_SIZE
            ),
            "page": int(page),
        },
        timeout=60,
        label=(
            "Common Crawl URL query "
            f"for {pattern} page {page}"
        ),
    )
    urls = parse_cdx_urls(
        response.text
    )

    time.sleep(REQUEST_DELAY_SECONDS)
    return urls


def is_plausible_identifier(identifier):
    if not identifier:
        return False

    identifier = unquote(
        identifier
    ).strip()
    lowered = identifier.lower()

    if lowered in RESERVED_IDENTIFIERS:
        return False

    if not IDENTIFIER_PATTERN.fullmatch(
        identifier
    ):
        return False

    if lowered.endswith(
        FILE_LIKE_SUFFIXES
    ):
        return False

    if len(identifier) < 3:
        return False

    if identifier.isdigit():
        return False

    return True


def normalize_board_record(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return None

    hostname = (
        parsed.hostname
        or ""
    ).lower()

    if hostname.endswith(
        ".myworkdayjobs.com"
    ):
        try:
            board = (
                WorkdayCrawler
                .parse_board_url(url)
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

        site = str(
            board.get("site")
            or ""
        ).strip()
        lowered_site = site.lower()

        if (
            not site
            or lowered_site
            in RESERVED_IDENTIFIERS
            or re.fullmatch(
                r"[a-z]{2}",
                lowered_site,
            )
        ):
            return None

        canonical_url = (
            board["canonical_url"]
        )

        return {
            "source_type": "workday",
            "source_identifier": (
                canonical_url
            ),
            "url": canonical_url,
            "key": (
                "workday",
                canonical_url.lower(),
            ),
        }

    path_parts = [
        unquote(part).strip()
        for part in parsed.path.split("/")
        if part.strip()
    ]

    if not path_parts:
        return None

    board_identifier = path_parts[0]

    if not is_plausible_identifier(
        board_identifier
    ):
        return None

    if hostname in {
        "jobs.lever.co",
        "jobs.eu.lever.co",
    }:
        source_type = "lever"
        normalized_url = (
            f"https://{hostname}/"
            f"{board_identifier}"
        )

    elif hostname in {
        "job-boards.greenhouse.io",
        "boards.greenhouse.io",
    }:
        source_type = "greenhouse"
        normalized_url = (
            "https://job-boards.greenhouse.io/"
            f"{board_identifier}"
        )

    elif hostname == "jobs.ashbyhq.com":
        source_type = "ashby"
        normalized_url = (
            "https://jobs.ashbyhq.com/"
            f"{board_identifier}"
        )

    else:
        return None

    return {
        "source_type": source_type,
        "source_identifier": (
            board_identifier
        ),
        "url": normalized_url,
        "key": (
            source_type,
            board_identifier.lower(),
        ),
    }


def normalize_board_url(url):
    record = normalize_board_record(url)

    if record is None:
        return None

    return record["url"]


def load_known_board_keys():
    active_keys = {
        (
            str(source_type).lower(),
            str(identifier).lower(),
        )
        for source_type, identifier
        in db.session.query(
            JobSourceCompany.source_type,
            JobSourceCompany.source_identifier,
        ).all()
        if source_type and identifier
    }

    candidate_statuses = {
        (
            str(source_type).lower(),
            str(identifier).lower(),
        ): str(status or "").lower()
        for (
            source_type,
            identifier,
            status,
        )
        in db.session.query(
            JobSourceCandidate.source_type,
            JobSourceCandidate.source_identifier,
            JobSourceCandidate.validation_status,
        ).all()
        if source_type and identifier
    }

    return (
        active_keys,
        candidate_statuses,
    )


def discover_new_board_pool(
    source_type,
    patterns,
    index_endpoints,
    active_keys,
    candidate_statuses,
    maximum_candidates,
):
    new_records = {}
    known_counts = {
        "already_active": 0,
        "already_candidate": 0,
        "already_blocked": 0,
        "already_approved": 0,
    }
    seen_known_keys = set()
    raw_url_count = 0
    rejected_count = 0
    pages_scanned = 0
    failures = []

    for index_endpoint in index_endpoints:
        if len(new_records) >= maximum_candidates:
            break

        for pattern in patterns:
            if len(new_records) >= maximum_candidates:
                break

            try:
                page_count = fetch_page_count(
                    index_endpoint,
                    pattern,
                )
                pages = select_sample_pages(
                    page_count,
                )

                print(
                    "AUTOMATIC DISCOVERY SAMPLE | "
                    f"Source: {source_type} | "
                    f"Pattern: {pattern} | "
                    f"Available pages: "
                    f"{page_count} | "
                    f"Selected pages: {pages}"
                )

                for page in pages:
                    if (
                        len(new_records)
                        >= maximum_candidates
                    ):
                        break

                    raw_urls = (
                        fetch_common_crawl_page(
                            index_endpoint,
                            pattern,
                            page,
                        )
                    )
                    pages_scanned += 1
                    raw_url_count += len(
                        raw_urls
                    )

                    for raw_url in raw_urls:
                        record = (
                            normalize_board_record(
                                raw_url
                            )
                        )

                        if (
                            record is None
                            or record[
                                "source_type"
                            ] != source_type
                        ):
                            rejected_count += 1
                            continue

                        key = record["key"]

                        if key in active_keys:
                            if (
                                key
                                not in seen_known_keys
                            ):
                                known_counts[
                                    "already_active"
                                ] += 1
                                seen_known_keys.add(
                                    key
                                )
                            continue

                        candidate_status = (
                            candidate_statuses.get(
                                key
                            )
                        )

                        if candidate_status:
                            if (
                                key
                                not in seen_known_keys
                            ):
                                if candidate_status in {
                                    "dismissed",
                                    "rejected",
                                    "invalid",
                                }:
                                    status_key = (
                                        "already_blocked"
                                    )
                                elif (
                                    candidate_status
                                    == "approved"
                                ):
                                    status_key = (
                                        "already_approved"
                                    )
                                else:
                                    status_key = (
                                        "already_candidate"
                                    )

                                known_counts[
                                    status_key
                                ] += 1
                                seen_known_keys.add(
                                    key
                                )
                            continue

                        new_records.setdefault(
                            key,
                            record,
                        )

                        if (
                            len(new_records)
                            >= maximum_candidates
                        ):
                            break

            except Exception as error:
                failures.append(
                    f"{pattern}: {error}"
                )

                print(
                    "AUTOMATIC DISCOVERY "
                    "PATTERN FAILED | "
                    f"Source: {source_type} | "
                    f"Pattern: {pattern} | "
                    f"Error: {error}"
                )

    return {
        "records": list(
            new_records.values()
        ),
        "known_counts": known_counts,
        "raw_url_count": raw_url_count,
        "rejected_count": rejected_count,
        "pages_scanned": pages_scanned,
        "failures": failures,
    }


def empty_ingestion_results():
    return {
        "created": 0,
        "already_active": 0,
        "already_candidate": 0,
        "already_blocked": 0,
        "already_approved": 0,
        "invalid_rejected": 0,
        "failed": 0,
    }


def add_result_counts(target, source):
    for key in target:
        target[key] += int(
            source.get(key, 0)
            or 0
        )


def validate_discovered_records(
    source_type,
    records,
    target_valid_count,
    maximum_attempts,
):
    results = empty_ingestion_results()
    attempted = 0

    for record in records:
        if attempted >= maximum_attempts:
            break

        if (
            results["created"]
            >= target_valid_count
        ):
            break

        attempted += 1

        try:
            with db.session.begin_nested():
                _, status = ingest_source_url(
                    url=record["url"],
                    discovery_method=(
                        "common_crawl"
                    ),
                    auto_validate=True,
                    keep_invalid=False,
                )

            if status in results:
                results[status] += 1
            else:
                results["failed"] += 1

        except Exception as error:
            results["failed"] += 1

            print(
                "AUTOMATIC SOURCE "
                "INGESTION FAILED | "
                f"Source: {source_type} | "
                f"URL: {record['url']} | "
                f"Error: {error}"
            )

    print(
        "AUTOMATIC DISCOVERY VALIDATION | "
        f"Source: {source_type} | "
        f"Attempted: {attempted} | "
        f"Valid: {results['created']} | "
        f"Invalid: "
        f"{results['invalid_rejected']} | "
        f"Failed: {results['failed']}"
    )

    return results


def run_common_crawl_discovery(
    limit_per_source=20,
):
    requested_limit = max(
        1,
        int(limit_per_source),
    )
    validation_attempt_limit = min(
        requested_limit,
        MAX_VALIDATION_ATTEMPTS_PER_SOURCE,
    )
    target_valid_count = min(
        validation_attempt_limit,
        TARGET_VALID_BOARDS_PER_SOURCE,
    )
    candidate_pool_limit = max(
        validation_attempt_limit * 4,
        40,
    )

    index_endpoints = (
        get_common_crawl_indexes()
    )
    (
        active_keys,
        candidate_statuses,
    ) = load_known_board_keys()

    total_results = (
        empty_ingestion_results()
    )
    source_counts = {
        source_type: 0
        for source_type
        in DISCOVERY_PATTERNS
    }
    rejected_counts = {
        source_type: 0
        for source_type
        in DISCOVERY_PATTERNS
    }
    source_failures = {}
    discovery_details = {}

    for source_type, patterns in (
        DISCOVERY_PATTERNS.items()
    ):
        print(
            "AUTOMATIC DISCOVERY: "
            f"searching broad Common Crawl "
            f"samples for {source_type}."
        )

        discovery = (
            discover_new_board_pool(
                source_type=source_type,
                patterns=patterns,
                index_endpoints=(
                    index_endpoints
                ),
                active_keys=active_keys,
                candidate_statuses=(
                    candidate_statuses
                ),
                maximum_candidates=(
                    candidate_pool_limit
                ),
            )
        )
        records = discovery["records"]
        source_counts[source_type] = len(
            records
        )
        rejected_counts[source_type] = (
            discovery["rejected_count"]
        )

        add_result_counts(
            total_results,
            discovery["known_counts"],
        )

        if discovery["failures"]:
            source_failures[source_type] = (
                discovery["failures"]
            )

        source_results = (
            validate_discovered_records(
                source_type=source_type,
                records=records,
                target_valid_count=(
                    target_valid_count
                ),
                maximum_attempts=(
                    validation_attempt_limit
                ),
            )
        )
        add_result_counts(
            total_results,
            source_results,
        )

        discovery_details[source_type] = {
            "raw_urls": (
                discovery["raw_url_count"]
            ),
            "pages_scanned": (
                discovery["pages_scanned"]
            ),
            "new_pool": len(records),
            "valid_created": (
                source_results["created"]
            ),
        }

        print(
            "AUTOMATIC DISCOVERY FILTER | "
            f"Source: {source_type} | "
            f"Raw URLs: "
            f"{discovery['raw_url_count']} | "
            f"Pages scanned: "
            f"{discovery['pages_scanned']} | "
            f"New board pool: "
            f"{len(records)} | "
            f"Rejected URL records: "
            f"{discovery['rejected_count']}"
        )

    db.session.commit()

    return {
        "found": sum(
            source_counts.values()
        ),
        "by_source": source_counts,
        "rejected_by_source": (
            rejected_counts
        ),
        "source_failures": (
            source_failures
        ),
        "details": discovery_details,
        **total_results,
    }
