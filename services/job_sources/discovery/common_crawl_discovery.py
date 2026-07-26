
import json
import re
import time
from urllib.parse import unquote, urlparse

from services.job_sources.discovery.candidate_service import (
    ingest_source_urls
)
from services.job_sources.http_client import fetch_response


COMMON_CRAWL_INDEX = (
    "https://index.commoncrawl.org/CC-MAIN-2026-25-index"
)

DISCOVERY_PATTERNS = {
    "lever": "jobs.lever.co/*",
    "greenhouse": "job-boards.greenhouse.io/*",
    "ashby": "jobs.ashbyhq.com/*"
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
    "search",
    "sitemap",
    "sitemap.xml",
    "static",
    "terms"
}

IDENTIFIER_PATTERN = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,99}$"
)

DISCOVERY_PAGE_STATE = {
    "lever": 0,
    "greenhouse": 0,
    "ashby": 0
}



def fetch_common_crawl_urls(
    pattern,
    limit=20,
    page=0,
    max_attempts=3
):
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = fetch_response(
                COMMON_CRAWL_INDEX,
                params={
                    "url": pattern,
                    "output": "json",
                    "filter": "status:200",
                    "collapse": "urlkey",
                    "limit": limit,
                    "page": page
                },
                timeout=60
            )

            discovered_urls = []

            for line in response.text.splitlines():
                line = line.strip()

                if not line:
                    continue

                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue

                url = record.get("url")

                if url:
                    discovered_urls.append(url)

            return discovered_urls

        except Exception as error:
            last_error = error

            print(
                f"COMMON CRAWL REQUEST FAILED | "
                f"Pattern: {pattern} | "
                f"Page: {page} | "
                f"Attempt: {attempt}/{max_attempts} | "
                f"Error: {error}"
            )

            if attempt < max_attempts:
                wait_seconds = attempt * 10

                print(
                    f"COMMON CRAWL RETRY | "
                    f"Waiting {wait_seconds} seconds."
                )

                time.sleep(wait_seconds)

    raise RuntimeError(
        f"Common Crawl failed after {max_attempts} attempts "
        f"for pattern {pattern} on page {page}: "
        f"{last_error}"
    )


def is_plausible_identifier(identifier):
    if not identifier:
        return False

    identifier = unquote(identifier).strip()
    lowered = identifier.lower()

    if lowered in RESERVED_IDENTIFIERS:
        return False

    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        return False

    # Reject filename-like paths that Common Crawl may capture.
    if lowered.endswith((
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
        ".xml"
    )):
        return False

    # Reject extremely short identifiers such as "0x" and "0g".
    if len(identifier) < 3:
        return False

    # Reject identifiers made only from numbers.
    if identifier.isdigit():
        return False

    return True


def normalize_board_url(url):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    path_parts = [
        unquote(part).strip()
        for part in parsed.path.split("/")
        if part.strip()
    ]

    if not path_parts:
        return None

    board_identifier = path_parts[0]

    if not is_plausible_identifier(board_identifier):
        return None

    if hostname in {
        "jobs.lever.co",
        "jobs.eu.lever.co"
    }:
        return f"https://{hostname}/{board_identifier}"

    if hostname in {
        "job-boards.greenhouse.io",
        "boards.greenhouse.io"
    }:
        return (
            f"https://job-boards.greenhouse.io/"
            f"{board_identifier}"
        )

    if hostname == "jobs.ashbyhq.com":
        return (
            f"https://jobs.ashbyhq.com/"
            f"{board_identifier}"
        )

    return None


def run_common_crawl_discovery(limit_per_source=20):
    all_board_urls = set()

    source_counts = {
        "lever": 0,
        "greenhouse": 0,
        "ashby": 0
    }

    rejected_counts = {
        "lever": 0,
        "greenhouse": 0,
        "ashby": 0
    }

    source_failures = {}

    for source_type, pattern in DISCOVERY_PATTERNS.items():
        current_page = DISCOVERY_PAGE_STATE[source_type]

        print(
            f"AUTOMATIC DISCOVERY: searching "
            f"Common Crawl for {source_type} "
            f"on page {current_page}."
        )

        try:
            raw_urls = fetch_common_crawl_urls(
                pattern=pattern,
                limit=limit_per_source,
                page=current_page
            )

            DISCOVERY_PAGE_STATE[source_type] += 1

        except Exception as error:
            source_failures[source_type] = str(error)

            print(
                f"AUTOMATIC DISCOVERY SOURCE FAILED | "
                f"Source: {source_type} | "
                f"Page: {current_page} | "
                f"Error: {error}"
            )

            continue

        normalized_urls = set()

        for raw_url in raw_urls:
            normalized_url = normalize_board_url(raw_url)

            if normalized_url:
                normalized_urls.add(normalized_url)
            else:
                rejected_counts[source_type] += 1

        source_counts[source_type] = len(normalized_urls)
        all_board_urls.update(normalized_urls)

        print(
            f"AUTOMATIC DISCOVERY FILTER | "
            f"Source: {source_type} | "
            f"Accepted: {len(normalized_urls)} | "
            f"Rejected: {rejected_counts[source_type]}"
        )

        time.sleep(5)

    ingestion_results = ingest_source_urls(
        urls=sorted(all_board_urls),
        discovery_method="common_crawl",
        auto_validate=True,
        keep_invalid=False
    )

    return {
        "found": len(all_board_urls),
        "by_source": source_counts,
        "rejected_by_source": rejected_counts,
        "source_failures": source_failures,
        **ingestion_results
    }
    