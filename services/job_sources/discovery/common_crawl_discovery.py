
import json
import time
from urllib.parse import urlparse

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


def fetch_common_crawl_urls(
    pattern,
    limit=250
):
    response = fetch_response(
        COMMON_CRAWL_INDEX,
        params={
            "url": pattern,
            "output": "json",
            "filter": "status:200",
            "collapse": "urlkey",
            "limit": limit
        }
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


def normalize_board_url(url):
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()

    path_parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]

    if not path_parts:
        return None

    board_identifier = path_parts[0]

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


def run_common_crawl_discovery(
    limit_per_source=250
):
    all_board_urls = set()
    source_counts = {}

    for source_type, pattern in DISCOVERY_PATTERNS.items():
        print(
            f"AUTOMATIC DISCOVERY: searching "
            f"Common Crawl for {source_type}."
        )

        raw_urls = fetch_common_crawl_urls(
            pattern=pattern,
            limit=limit_per_source
        )

        normalized_urls = {
            normalized
            for raw_url in raw_urls
            if (
                normalized := normalize_board_url(raw_url)
            )
        }

        source_counts[source_type] = len(
            normalized_urls
        )

        all_board_urls.update(normalized_urls)

        # Avoid hammering the shared Common Crawl API.
        time.sleep(2)

    ingestion_results = ingest_source_urls(
        urls=sorted(all_board_urls),
        discovery_method="common_crawl",
        auto_validate=True
    )

    return {
        "found": len(all_board_urls),
        "by_source": source_counts,
        **ingestion_results
    }
    