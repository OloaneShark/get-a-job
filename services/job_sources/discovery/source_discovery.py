
from urllib.parse import urlparse

from services.job_sources.source_utils import (
    extract_ashby_job_board_name,
    extract_greenhouse_board_token,
    extract_lever_company_slug
)


def detect_source_type(url):
    if not url or not url.strip():
        raise ValueError("A job-board URL is required.")

    cleaned_url = url.strip()

    if "://" not in cleaned_url:
        cleaned_url = f"https://{cleaned_url}"

    parsed = urlparse(cleaned_url)
    hostname = (parsed.hostname or "").lower()

    if hostname in {
        "jobs.lever.co",
        "jobs.eu.lever.co"
    }:
        return (
            "lever",
            extract_lever_company_slug(cleaned_url)
        )

    if hostname in {
        "boards.greenhouse.io",
        "job-boards.greenhouse.io"
    }:
        return (
            "greenhouse",
            extract_greenhouse_board_token(cleaned_url)
        )

    if hostname == "jobs.ashbyhq.com":
        return (
            "ashby",
            extract_ashby_job_board_name(cleaned_url)
        )

    raise ValueError(
        "Unsupported job-board URL. "
        "Currently supported: Greenhouse, Lever, and Ashby."
    )
    