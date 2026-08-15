
from urllib.parse import urlparse

from services.job_sources.source_utils import (
    extract_ashby_job_board_name,
    extract_greenhouse_board_token,
    extract_lever_company_slug,
    extract_bamboohr_company_subdomain,
    extract_workable_account_subdomain,
)
from services.job_sources.workday_crawler import (
    WorkdayCrawler,
)
from services.job_sources.recruitee import RecruiteeJobSource


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

    if hostname.endswith(
        ".myworkdayjobs.com"
    ):
        return (
            "workday",
            WorkdayCrawler.canonical_board_url(
                cleaned_url
            )
        )

    if hostname.endswith(
        ".recruitee.com"
    ):
        return (
            "recruitee",
            RecruiteeJobSource.extract_company_slug(
                cleaned_url
            )
        )

    if hostname.endswith(
        ".bamboohr.com"
    ):
        return (
            "bamboohr",
            extract_bamboohr_company_subdomain(
                cleaned_url
            )
        )

    if (
        hostname == "workable.com"
        or hostname.endswith(
            ".workable.com"
        )
    ):
        return (
            "workable",
            extract_workable_account_subdomain(
                cleaned_url
            )
        )

    raise ValueError(
        "Unsupported job-board URL. "
        "Currently supported: Greenhouse, Lever, Ashby, Workday, Recruitee, BambooHR, and Workable."
    )
    