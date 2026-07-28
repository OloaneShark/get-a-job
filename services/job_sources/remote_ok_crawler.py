
import json
import re
import time
import xml.etree.ElementTree as ET

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from services.job_sources.http_client import (
    clean_html_text,
    fetch_response,
)


REMOTE_OK_BASE_URL = "https://remoteok.com"
REMOTE_OK_SITEMAP_URL = (
    "https://remoteok.com/sitemap.xml"
)

MAX_JOB_AGE_DAYS = 30

# Keep this bounded so Remote OK does not get hammered.
MAX_JOB_PAGES_PER_RUN = 300

# Remote OK asks crawlers to wait at least one second.
REQUEST_DELAY_SECONDS = 1.1

REMOTE_OK_JOB_PATH_PREFIX = "/remote-jobs/"

# We grab a newer slice first, then rank that slice by relevance.
# This keeps some ancient perfect keyword match from wasting the run.
MIN_RECENT_POOL_SIZE = 500
RECENT_POOL_MULTIPLIER = 20


def utc_now():
    return datetime.now(timezone.utc)


def get_cutoff_datetime(
    max_age_days=MAX_JOB_AGE_DAYS,
):
    return utc_now() - timedelta(
        days=max_age_days
    )


def normalize_datetime(value):
    if not value:
        return None

    if isinstance(value, datetime):
        parsed_value = value
    else:
        text = str(value).strip()

        if not text:
            return None

        # Python does not always like the Z ending,
        # so turn it into a normal UTC offset first.
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        try:
            parsed_value = datetime.fromisoformat(
                text
            )
        except ValueError:
            try:
                parsed_value = datetime.strptime(
                    text[:10],
                    "%Y-%m-%d",
                )
            except ValueError:
                return None

    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(
            tzinfo=timezone.utc
        )

    return parsed_value.astimezone(
        timezone.utc
    )


def is_recent_datetime(
    value,
    max_age_days=MAX_JOB_AGE_DAYS,
):
    parsed_value = normalize_datetime(
        value
    )

    if parsed_value is None:
        return False

    return parsed_value >= get_cutoff_datetime(
        max_age_days
    )


def normalize_slug_text(url):
    parsed_url = urlparse(url)

    slug = (
        parsed_url.path
        .rstrip("/")
        .split("/")[-1]
    )

    slug = re.sub(
        r"-\d+$",
        "",
        slug,
    )

    slug = slug.replace(
        "-",
        " ",
    )

    return re.sub(
        r"\s+",
        " ",
        slug,
    ).strip().lower()


def is_remote_ok_job_url(url):
    try:
        parsed_url = urlparse(url)
    except ValueError:
        return False

    hostname = (
        parsed_url.hostname
        or ""
    ).lower()

    if hostname not in {
        "remoteok.com",
        "www.remoteok.com",
    }:
        return False

    path = parsed_url.path.rstrip("/")

    # A real Remote OK job URL uses this path and ends
    # with the numeric Remote OK job ID.
    return bool(
        path.startswith(
            REMOTE_OK_JOB_PATH_PREFIX
        )
        and re.search(
            r"-\d+$",
            path,
        )
    )


def extract_external_id(url):
    parsed_url = urlparse(url)

    slug = (
        parsed_url.path
        .rstrip("/")
        .split("/")[-1]
    )

    match = re.search(
        r"-(\d+)$",
        slug,
    )

    if not match:
        return None

    return match.group(1)


def extract_external_id_number(url):
    external_id = extract_external_id(
        url
    )

    if not external_id:
        return 0

    try:
        return int(external_id)
    except ValueError:
        return 0


def parse_keyword_values(value):
    if not value:
        return []

    if isinstance(
        value,
        (list, tuple, set),
    ):
        raw_values = value
    else:
        raw_values = str(value).split(",")

    normalized_values = []

    for item in raw_values:
        text = str(item).strip().lower()

        if not text:
            continue

        text = text.replace(
            "-",
            " ",
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if text not in normalized_values:
            normalized_values.append(text)

    return normalized_values


def score_slug_for_profile(
    slug_text,
    profile_keywords,
):
    if not slug_text:
        return 0

    generic_keywords = {
        "developer",
        "engineer",
        "software",
        "web",
    }

    score = 0

    for keyword in profile_keywords:
        if keyword in generic_keywords:
            continue

        if keyword not in slug_text:
            continue

        # Longer phrases deserve more weight than one broad word.
        score += max(
            1,
            len(keyword.split()),
        )

    return score


def parse_sitemap_document(xml_text):
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise RuntimeError(
            "Remote OK sitemap could not "
            f"be parsed: {error}"
        ) from error

    root_name = root.tag.split("}")[-1]

    sitemap_urls = []
    job_entries = []

    if root_name == "sitemapindex":
        for sitemap_element in root:
            child_name = (
                sitemap_element.tag
                .split("}")[-1]
            )

            if child_name != "sitemap":
                continue

            location = None
            last_modified = None

            for child in sitemap_element:
                field_name = (
                    child.tag
                    .split("}")[-1]
                )

                if field_name == "loc":
                    location = (
                        child.text
                        or ""
                    ).strip()

                elif field_name == "lastmod":
                    last_modified = (
                        child.text
                        or ""
                    ).strip()

            if location:
                sitemap_urls.append({
                    "url": location,
                    "last_modified": last_modified,
                })

    elif root_name == "urlset":
        for url_element in root:
            child_name = (
                url_element.tag
                .split("}")[-1]
            )

            if child_name != "url":
                continue

            location = None
            last_modified = None

            for child in url_element:
                field_name = (
                    child.tag
                    .split("}")[-1]
                )

                if field_name == "loc":
                    location = (
                        child.text
                        or ""
                    ).strip()

                elif field_name == "lastmod":
                    last_modified = (
                        child.text
                        or ""
                    ).strip()

            if location:
                job_entries.append({
                    "url": location,
                    "last_modified": last_modified,
                })

    return {
        "sitemaps": sitemap_urls,
        "jobs": job_entries,
    }


def fetch_sitemap(url):
    response = fetch_response(
        url,
        timeout=60,
    )

    return parse_sitemap_document(
        response.text
    )


def discover_recent_job_urls(
    profile=None,
    max_age_days=MAX_JOB_AGE_DAYS,
    max_job_urls=MAX_JOB_PAGES_PER_RUN,
):
    pending_sitemaps = [
        REMOTE_OK_SITEMAP_URL
    ]

    visited_sitemaps = set()
    discovered_jobs = {}

    total_url_entries = 0
    rejected_url_entries = 0

    while pending_sitemaps:
        sitemap_url = pending_sitemaps.pop(0)

        if sitemap_url in visited_sitemaps:
            continue

        visited_sitemaps.add(
            sitemap_url
        )

        print(
            "REMOTE OK SITEMAP: fetching "
            f"{sitemap_url}"
        )

        sitemap_data = fetch_sitemap(
            sitemap_url
        )

        for child_sitemap in sitemap_data[
            "sitemaps"
        ]:
            child_url = child_sitemap["url"]

            if "/sitemap-jobs-" not in child_url:
                print(
                    "REMOTE OK SITEMAP SKIPPED: "
                    f"{child_url}"
                )
                continue

            if child_url not in visited_sitemaps:
                pending_sitemaps.append(
                    child_url
                )

        for entry in sitemap_data["jobs"]:
            total_url_entries += 1

            job_url = entry["url"]

            if not is_remote_ok_job_url(
                job_url
            ):
                rejected_url_entries += 1
                continue

            if job_url in discovered_jobs:
                continue

            last_modified = normalize_datetime(
                entry.get("last_modified")
            )

            discovered_jobs[job_url] = {
                "url": job_url,
                "last_modified": last_modified,
            }

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print(
        "REMOTE OK SITEMAP SUMMARY | "
        f"URL entries: {total_url_entries} | "
        f"Valid job URLs: "
        f"{len(discovered_jobs)} | "
        f"Rejected URLs: "
        f"{rejected_url_entries}"
    )

    job_entries = list(
        discovered_jobs.values()
    )

    print(
        "REMOTE OK DISCOVERY POOL | "
        "Eligible URLs before page verification: "
        f"{len(job_entries)}"
    )

    profile_keywords = parse_keyword_values(
        getattr(
            profile,
            "keywords",
            None,
        )
    )

    for entry in job_entries:
        slug_text = normalize_slug_text(
            entry["url"]
        )

        entry["slug_text"] = slug_text
        entry["external_id_number"] = (
            extract_external_id_number(
                entry["url"]
            )
        )
        entry["keyword_score"] = (
            score_slug_for_profile(
                slug_text,
                profile_keywords,
            )
        )

        last_modified = entry.get(
            "last_modified"
        )

        entry["last_modified_timestamp"] = (
            last_modified.timestamp()
            if last_modified
            else 0
        )

        entry["sitemap_recent"] = bool(
            last_modified
            and is_recent_datetime(
                last_modified,
                max_age_days=max_age_days,
            )
        )

    recent_pool_size = min(
        len(job_entries),
        max(
            max_job_urls
            * RECENT_POOL_MULTIPLIER,
            MIN_RECENT_POOL_SIZE,
        ),
    )

    # First get the newest-looking jobs. Remote OK IDs usually
    # increase over time, and sitemap lastmod helps when it exists.
    job_entries.sort(
        key=lambda entry: (
            entry.get(
                "sitemap_recent",
                False,
            ),
            entry.get(
                "last_modified_timestamp",
                0,
            ),
            entry.get(
                "external_id_number",
                0,
            ),
        ),
        reverse=True,
    )

    recent_candidate_pool = job_entries[
        :recent_pool_size
    ]

    print(
        "REMOTE OK RECENT POOL | "
        "Candidates kept before keyword ranking: "
        f"{len(recent_candidate_pool)} | "
        f"Original pool: {len(job_entries)}"
    )

    # Now rank the newer pool by the user's profile.
    recent_candidate_pool.sort(
        key=lambda entry: (
            entry.get(
                "keyword_score",
                0,
            ),
            entry.get(
                "sitemap_recent",
                False,
            ),
            entry.get(
                "last_modified_timestamp",
                0,
            ),
            entry.get(
                "external_id_number",
                0,
            ),
        ),
        reverse=True,
    )

    selected_entries = (
        recent_candidate_pool[
            :max_job_urls
        ]
    )

    print(
        "REMOTE OK SITEMAP SELECTION | "
        f"Selected: {len(selected_entries)} | "
        f"Page limit: {max_job_urls}"
    )

    for entry in selected_entries:
        print(
            "REMOTE OK CANDIDATE SELECTED | "
            f"Score: "
            f"{entry.get('keyword_score', 0)} | "
            f"Sitemap recent: "
            f"{entry.get('sitemap_recent', False)} | "
            f"Last modified: "
            f"{entry.get('last_modified')} | "
            f"Job ID: "
            f"{entry.get('external_id_number', 0)} | "
            f"Slug: "
            f"{entry.get('slug_text')} | "
            f"URL: "
            f"{entry.get('url')}"
        )

    return selected_entries


def find_job_posting_json_ld(soup):
    scripts = soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        },
    )

    for script in scripts:
        raw_json = (
            script.string
            or script.get_text()
        )

        if not raw_json:
            continue

        try:
            payload = json.loads(
                raw_json
            )
        except json.JSONDecodeError:
            continue

        candidates = []

        if isinstance(payload, dict):
            candidates.append(
                payload
            )

            graph = payload.get(
                "@graph"
            )

            if isinstance(graph, list):
                candidates.extend(
                    graph
                )

        elif isinstance(payload, list):
            candidates.extend(
                payload
            )

        for candidate in candidates:
            if not isinstance(
                candidate,
                dict,
            ):
                continue

            candidate_type = candidate.get(
                "@type"
            )

            if candidate_type == "JobPosting":
                return candidate

            if (
                isinstance(
                    candidate_type,
                    list,
                )
                and "JobPosting"
                in candidate_type
            ):
                return candidate

    return None


def unique_values(values):
    results = []

    for value in values:
        if (
            value
            and value not in results
        ):
            results.append(value)

    return results


def extract_location_details(
    job_posting,
):
    explicit_locations = []
    applicant_locations = []

    job_location = job_posting.get(
        "jobLocation"
    )

    if isinstance(job_location, dict):
        job_location = [
            job_location
        ]

    if isinstance(job_location, list):
        for location_item in job_location:
            if not isinstance(
                location_item,
                dict,
            ):
                continue

            address = location_item.get(
                "address"
            )

            if not isinstance(
                address,
                dict,
            ):
                continue

            address_parts = [
                address.get(
                    "addressLocality"
                ),
                address.get(
                    "addressRegion"
                ),
                address.get(
                    "addressCountry"
                ),
            ]

            address_text = ", ".join(
                str(part).strip()
                for part in address_parts
                if part
            )

            if address_text:
                explicit_locations.append(
                    address_text
                )

    applicant_requirements = job_posting.get(
        "applicantLocationRequirements"
    )

    if isinstance(
        applicant_requirements,
        dict,
    ):
        applicant_requirements = [
            applicant_requirements
        ]

    if isinstance(
        applicant_requirements,
        list,
    ):
        for requirement in applicant_requirements:
            if not isinstance(
                requirement,
                dict,
            ):
                continue

            name = requirement.get(
                "name"
            )

            if name:
                applicant_locations.append(
                    str(name).strip()
                )

    explicit_locations = unique_values(
        explicit_locations
    )

    applicant_locations = unique_values(
        applicant_locations
    )

    if explicit_locations:
        location = " | ".join(
            explicit_locations
        )

        return {
            "value": location,
            "raw_value": location,
            "source": (
                "remote_ok_json_ld_job_location"
            ),
            "confidence": 0.95,
        }

    if applicant_locations:
        location = " | ".join(
            applicant_locations
        )

        normalized_location = (
            location.strip().lower()
        )

        generic_applicant_values = {
            "anywhere",
            "anywhere in the world",
            "worldwide",
            "global",
            "remote",
        }

        confidence = (
            0.85
            if normalized_location
            not in generic_applicant_values
            else 0.75
        )

        return {
            "value": location,
            "raw_value": location,
            "source": (
                "remote_ok_json_ld_applicant_location"
            ),
            "confidence": confidence,
        }

    return {
        "value": "Remote",
        "raw_value": None,
        "source": (
            "remote_ok_json_ld_fallback"
        ),
        "confidence": 0.35,
    }


def extract_employment_type(value):
    if isinstance(value, list):
        value = (
            value[0]
            if value
            else None
        )

    value = str(
        value
        or ""
    ).strip().lower()

    mappings = {
        "full_time": "Full-time",
        "full-time": "Full-time",
        "full time": "Full-time",
        "part_time": "Part-time",
        "part-time": "Part-time",
        "part time": "Part-time",
        "contractor": "Contract",
        "contract": "Contract",
        "temporary": "Temporary",
        "intern": "Internship",
        "internship": "Internship",
    }

    return mappings.get(
        value,
        value.title()
        if value
        else None,
    )


def format_salary_number(value):
    if value is None:
        return None

    if isinstance(value, bool):
        return str(value)

    if isinstance(value, (int, float)):
        return f"{value:,}"

    return str(value).strip()


def extract_salary(job_posting):
    base_salary = job_posting.get(
        "baseSalary"
    )

    if not isinstance(
        base_salary,
        dict,
    ):
        return None

    currency = (
        base_salary.get("currency")
        or "USD"
    )

    salary_value = base_salary.get(
        "value"
    )

    if not isinstance(
        salary_value,
        dict,
    ):
        return None

    minimum = format_salary_number(
        salary_value.get("minValue")
    )

    maximum = format_salary_number(
        salary_value.get("maxValue")
    )

    unit_text = salary_value.get(
        "unitText"
    )

    suffix = ""

    if unit_text:
        suffix = (
            f" {str(unit_text).lower()}"
        )

    if (
        minimum is not None
        and maximum is not None
    ):
        return (
            f"{currency} {minimum} - "
            f"{maximum}{suffix}"
        )

    if minimum is not None:
        return (
            f"{currency} "
            f"{minimum}+{suffix}"
        )

    if maximum is not None:
        return (
            f"Up to {currency} "
            f"{maximum}{suffix}"
        )

    return None


def fetch_and_normalize_job(
    url,
    sitemap_last_modified=None,
    max_age_days=MAX_JOB_AGE_DAYS,
):
    response = fetch_response(
        url,
        timeout=60,
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    job_posting = find_job_posting_json_ld(
        soup
    )

    if not job_posting:
        print(
            "REMOTE OK PAGE REJECTED | "
            "No JobPosting JSON-LD: "
            f"{url}"
        )
        return None

    published_at = normalize_datetime(
        job_posting.get("datePosted")
    )

    if not published_at:
        print(
            "REMOTE OK PAGE REJECTED | "
            f"No datePosted value: {url}"
        )
        return None

    if not is_recent_datetime(
        published_at,
        max_age_days=max_age_days,
    ):
        print(
            "REMOTE OK PAGE TOO OLD | "
            f"Date: {published_at.isoformat()} | "
            f"URL: {url}"
        )
        return None

    hiring_organization = job_posting.get(
        "hiringOrganization"
    )

    company_name = None

    if isinstance(
        hiring_organization,
        dict,
    ):
        company_name = (
            hiring_organization.get(
                "name"
            )
        )

    description = clean_html_text(
        job_posting.get(
            "description"
        )
    )

    title = str(
        job_posting.get("title")
        or ""
    ).strip()

    if not title:
        print(
            "REMOTE OK PAGE REJECTED | "
            f"No title value: {url}"
        )
        return None

    location_details = (
        extract_location_details(
            job_posting
        )
    )

    return {
        "source": "Remote OK",
        "external_id": extract_external_id(
            url
        ),
        "company_name": (
            company_name
            or "Unknown Company"
        ),
        "position_title": title,
        "location": location_details[
            "value"
        ],
        "location_raw": location_details[
            "raw_value"
        ],
        "location_source": location_details[
            "source"
        ],
        "location_confidence": (
            location_details[
                "confidence"
            ]
        ),
        "employment_type": (
            extract_employment_type(
                job_posting.get(
                    "employmentType"
                )
            )
        ),
        "salary": extract_salary(
            job_posting
        ),
        "visa_sponsorship": "unknown",
        "posting_url": url,
        "apply_url": url,
        "job_description": description,
        "departments": [],
        "offices": [],
        "is_remote": True,
        "workplace_type": "Remote",
        "published_at": published_at,
        "sitemap_last_modified": (
            normalize_datetime(
                sitemap_last_modified
            )
        ),
        "recruiter_name": None,
        "recruiter_email": None,
        "recruiter_contact_url": None,
        "recruiter_contact_source": None,
    }


def crawl_recent_remote_ok_jobs(
    profile=None,
    max_age_days=MAX_JOB_AGE_DAYS,
    max_job_pages=MAX_JOB_PAGES_PER_RUN,
):
    discovered_entries = (
        discover_recent_job_urls(
            profile=profile,
            max_age_days=max_age_days,
            max_job_urls=max_job_pages,
        )
    )

    print(
        "REMOTE OK CRAWL: "
        f"{len(discovered_entries)} ranked "
        "candidate URLs selected for verification."
    )

    normalized_jobs = []

    for index, entry in enumerate(
        discovered_entries,
        start=1,
    ):
        url = entry["url"]

        print(
            "REMOTE OK CRAWL PAGE "
            f"{index}/"
            f"{len(discovered_entries)}: "
            f"{url}"
        )

        try:
            job = fetch_and_normalize_job(
                url=url,
                sitemap_last_modified=(
                    entry.get(
                        "last_modified"
                    )
                ),
                max_age_days=max_age_days,
            )

            if job:
                normalized_jobs.append(
                    job
                )

                print(
                    "REMOTE OK NORMALIZED JOB | "
                    f"Title: "
                    f"{job.get('position_title')} | "
                    f"Company: "
                    f"{job.get('company_name')} | "
                    f"Location: "
                    f"{job.get('location')} | "
                    f"Location source: "
                    f"{job.get('location_source')} | "
                    f"Location confidence: "
                    f"{job.get('location_confidence')} | "
                    f"Published: "
                    f"{job.get('published_at')}"
                )

        except Exception as error:
            print(
                "REMOTE OK CRAWL ERROR | "
                f"URL: {url} | "
                f"Error: {error}"
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print(
        "REMOTE OK CRAWL COMPLETE | "
        f"Selected candidates: "
        f"{len(discovered_entries)} | "
        f"Normalized recent jobs: "
        f"{len(normalized_jobs)}"
    )

    return normalized_jobs
