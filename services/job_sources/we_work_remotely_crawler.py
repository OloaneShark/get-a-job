
import json
import re
import time

from datetime import (
    datetime,
    timedelta,
    timezone,
)
from html.parser import HTMLParser
from urllib.parse import (
    urljoin,
    urlparse,
)

from services.job_sources.http_client import (
    clean_html_text,
    fetch_html,
)


BASE_URL = "https://weworkremotely.com"

MAX_JOB_AGE_DAYS = 30
MAX_JOB_PAGES_PER_RUN = 20
REQUEST_DELAY_SECONDS = 1.0


DISCOVERY_URL = (
    "https://weworkremotely.com/"
    "remote-jobs/all-jobs"
)


ENTRY_LEVEL_URL_TERMS = {
    "intern": 10,
    "internship": 10,
    "junior": 10,
    "entry": 10,
    "graduate": 8,
    "new-grad": 8,
    "associate": 4,
}

SENIOR_URL_TERMS = {
    "senior": -12,
    "staff": -14,
    "principal": -14,
    "lead": -10,
    "manager": -12,
    "director": -14,
    "head": -14,
    "vp": -14,
}


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(
        self,
        tag,
        attributes,
    ):
        if tag.lower() != "a":
            return

        href = None

        for name, value in attributes:
            if name.lower() == "href":
                href = value
                break

        if href:
            self.links.append(href)


class VisibleTextCollector(HTMLParser):
    ignored_tags = {
        "script",
        "style",
        "svg",
        "noscript",
    }

    block_tags = {
        "article",
        "aside",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "ul",
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored_depth = 0

    def handle_starttag(
        self,
        tag,
        attributes,
    ):
        normalized_tag = tag.lower()

        if normalized_tag in self.ignored_tags:
            self.ignored_depth += 1
            return

        if (
            self.ignored_depth == 0
            and normalized_tag in self.block_tags
        ):
            self.parts.append("\n")

    def handle_endtag(
        self,
        tag,
    ):
        normalized_tag = tag.lower()

        if normalized_tag in self.ignored_tags:
            if self.ignored_depth > 0:
                self.ignored_depth -= 1

            return

        if (
            self.ignored_depth == 0
            and normalized_tag in self.block_tags
        ):
            self.parts.append("\n")

    def handle_data(
        self,
        data,
    ):
        if self.ignored_depth > 0:
            return

        value = str(
            data or ""
        ).strip()

        if value:
            self.parts.append(value)

    def get_text(self):
        text = " ".join(
            self.parts
        )

        text = re.sub(
            r"[ \t]+",
            " ",
            text,
        )

        text = re.sub(
            r" *\n *",
            "\n",
            text,
        )

        text = re.sub(
            r"\n{3,}",
            "\n\n",
            text,
        )

        return text.strip()


def normalize_text(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().lower(),
    )


def extract_visible_text(html):
    parser = VisibleTextCollector()

    try:
        parser.feed(
            html
        )
    except Exception:
        return clean_html_text(
            html
        ) or ""

    return parser.get_text()


def extract_page_title(html):
    match = re.search(
        r"<title[^>]*>(.*?)</title>",
        html,
        flags=(
            re.IGNORECASE
            | re.DOTALL
        ),
    )

    if not match:
        return None

    return clean_html_text(
        match.group(1)
    )


def split_wwr_page_title(
    page_title,
):
    text = clean_html_text(
        page_title
    ) or ""

    text = re.sub(
        r"\s+",
        " ",
        text,
    ).strip()

    text = re.sub(
        r"^remote\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    if " at " not in text:
        return (
            "Unknown Company",
            text or "Untitled Position",
        )

    position_title, company_name = (
        text.rsplit(
            " at ",
            1,
        )
    )

    return (
        company_name.strip()
        or "Unknown Company",
        position_title.strip()
        or "Untitled Position",
    )


def normalize_posting_url(url):
    absolute_url = urljoin(
        BASE_URL,
        str(url or "").strip(),
    )

    parsed_url = urlparse(
        absolute_url
    )

    if parsed_url.netloc.lower() not in {
        "weworkremotely.com",
        "www.weworkremotely.com",
    }:
        return None

    path = parsed_url.path.rstrip("/")

    if not path.startswith(
        "/remote-jobs/"
    ):
        return None

    if path == "/remote-jobs":
        return None

    return (
        f"https://weworkremotely.com"
        f"{path}"
    )


def parse_profile_keywords(profile):
    value = getattr(
        profile,
        "keywords",
        "",
    )

    return [
        item.strip().lower()
        for item in re.split(
            r"[\n,]+",
            value or "",
        )
        if item.strip()
    ]


def contains_url_term(
    text,
    term,
):
    return bool(
        re.search(
            r"(?<!\w)"
            + re.escape(term)
            + r"(?!\w)",
            text,
        )
    )


def url_keyword_score(
    url,
    profile,
):
    path = urlparse(
        url
    ).path

    raw_slug = (
        path.replace(
            "/remote-jobs/",
            "",
        )
        .strip("/")
        .lower()
    )

    readable_slug = normalize_text(
        raw_slug.replace("-", " ")
    )

    score = 0

    for keyword in parse_profile_keywords(
        profile
    ):
        normalized_keyword = normalize_text(
            keyword
        )

        if not normalized_keyword:
            continue

        if normalized_keyword in readable_slug:
            score += 3

        keyword_parts = [
            part
            for part
            in normalized_keyword.split()
            if len(part) >= 3
        ]

        score += sum(
            1
            for part in keyword_parts
            if part in readable_slug
        )

    for term, adjustment in (
        ENTRY_LEVEL_URL_TERMS.items()
    ):
        readable_term = term.replace(
            "-",
            " ",
        )

        if (
            term in raw_slug
            or readable_term in readable_slug
        ):
            score += adjustment

    for term, adjustment in (
        SENIOR_URL_TERMS.items()
    ):
        if contains_url_term(
            readable_slug,
            term,
        ):
            score += adjustment

    return score


def discover_wwr_job_urls(
    profile,
    excluded_urls=None,
    max_job_urls=MAX_JOB_PAGES_PER_RUN,
):
    excluded_urls = {
        normalize_posting_url(url)
        for url in (excluded_urls or set())
        if normalize_posting_url(url)
    }

    print(
        f"WWR DISCOVERY PAGE: "
        f"fetching {DISCOVERY_URL}"
    )

    html = fetch_html(
        DISCOVERY_URL,
        timeout=60,
    )

    parser = LinkCollector()
    parser.feed(html)

    discovered_urls = set()

    for href in parser.links:
        normalized_url = (
            normalize_posting_url(
                href
            )
        )

        if not normalized_url:
            continue

        if normalized_url in excluded_urls:
            continue

        discovered_urls.add(
            normalized_url
        )

    ranked_urls = [
        {
            "url": url,
            "keyword_score": (
                url_keyword_score(
                    url,
                    profile,
                )
            ),
        }
        for url in discovered_urls
    ]

    ranked_urls.sort(
        key=lambda entry: (
            entry["keyword_score"],
            entry["url"],
        ),
        reverse=True,
    )

    selected_urls = ranked_urls[
        :max_job_urls
    ]

    print(
        f"WWR LISTING DISCOVERY | "
        f"Found: {len(discovered_urls)} | "
        f"Selected: {len(selected_urls)} | "
        f"Page limit: {max_job_urls}"
    )

    for entry in selected_urls:
        print(
            f"WWR CANDIDATE SELECTED | "
            f"Score: "
            f"{entry['keyword_score']} | "
            f"URL: {entry['url']}"
        )

    return selected_urls


def iter_json_ld_objects(value):
    if isinstance(value, dict):
        yield value

        for child_value in value.values():
            yield from iter_json_ld_objects(
                child_value
            )

    elif isinstance(value, list):
        for child_value in value:
            yield from iter_json_ld_objects(
                child_value
            )


def extract_json_ld_blocks(html):
    pattern = re.compile(
        r"<script\b[^>]*"
        r"type=[\"']application/ld\+json[\"']"
        r"[^>]*>(.*?)</script>",
        re.IGNORECASE | re.DOTALL,
    )

    parsed_objects = []

    for match in pattern.finditer(html):
        raw_json = (
            match.group(1)
            .strip()
        )

        if not raw_json:
            continue

        try:
            value = json.loads(
                raw_json
            )
        except json.JSONDecodeError:
            continue

        parsed_objects.extend(
            iter_json_ld_objects(
                value
            )
        )

    return parsed_objects


def find_job_posting_json_ld(html):
    for candidate in extract_json_ld_blocks(
        html
    ):
        object_type = candidate.get(
            "@type"
        )

        if isinstance(object_type, list):
            normalized_types = {
                normalize_text(item)
                for item in object_type
            }
        else:
            normalized_types = {
                normalize_text(
                    object_type
                )
            }

        if "jobposting" in normalized_types:
            return candidate

    return None


def parse_datetime(value):
    if not value:
        return None

    text = str(value).strip()

    if not text:
        return None

    normalized_text = re.sub(
        r"\s+UTC$",
        "+00:00",
        text,
        flags=re.IGNORECASE,
    )

    if normalized_text.endswith("Z"):
        normalized_text = (
            normalized_text[:-1]
            + "+00:00"
        )

    try:
        parsed_value = datetime.fromisoformat(
            normalized_text
        )
    except ValueError:
        parsed_value = None

    if parsed_value is None:
        formats = [
            "%Y-%m-%d %H:%M:%S %Z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for date_format in formats:
            try:
                parsed_value = (
                    datetime.strptime(
                        text,
                        date_format,
                    )
                )
                break
            except ValueError:
                continue

    if parsed_value is None:
        return None

    if parsed_value.tzinfo is None:
        parsed_value = parsed_value.replace(
            tzinfo=timezone.utc
        )

    return parsed_value.astimezone(
        timezone.utc
    )


def extract_relative_posted_date(
    visible_text,
):
    text = normalize_text(
        visible_text
    )

    now = datetime.now(
        timezone.utc
    )

    if re.search(
        r"\bposted\s+today\b",
        text,
    ):
        return now

    if re.search(
        r"\bposted\s+yesterday\b",
        text,
    ):
        return now - timedelta(
            days=1
        )

    match = re.search(
        r"\bposted\s+"
        r"(\d{1,3})\s+"
        r"days?\s+ago\b",
        text,
    )

    if match:
        return now - timedelta(
            days=int(
                match.group(1)
            )
        )

    match = re.search(
        r"\bposted\s+"
        r"(\d{1,3})\s+"
        r"hours?\s+ago\b",
        text,
    )

    if match:
        return now - timedelta(
            hours=int(
                match.group(1)
            )
        )

    return None


def extract_fallback_employment_type(
    visible_text,
):
    text = normalize_text(
        visible_text
    )

    patterns = [
        (
            r"\bjob\s+type\s+full[-\s]?time\b",
            "Full-time",
        ),
        (
            r"\bjob\s+type\s+part[-\s]?time\b",
            "Part-time",
        ),
        (
            r"\bjob\s+type\s+contract\b",
            "Contract",
        ),
        (
            r"\bjob\s+type\s+temporary\b",
            "Temporary",
        ),
        (
            r"\bjob\s+type\s+internship\b",
            "Internship",
        ),
    ]

    for pattern, employment_type in patterns:
        if re.search(
            pattern,
            text,
        ):
            return employment_type

    return "Full-time"


def extract_fallback_location(
    visible_text,
):
    text = normalize_text(
        visible_text
    )

    worldwide_terms = {
        "anywhere in the world",
        "worldwide",
        "remote worldwide",
        "global remote",
    }

    if any(
        term in text
        for term in worldwide_terms
    ):
        return "Worldwide"

    region_match = re.search(
        r"\bregion\s+"
        r"([a-z][a-z0-9 ,/&().\-]{2,80})"
        r"(?=\s+(?:apply now|"
        r"auto-apply|"
        r"related jobs|"
        r"about the job|"
        r"job type|"
        r"salary|"
        r"category)|$)",
        text,
        flags=re.IGNORECASE,
    )

    if region_match:
        region = clean_html_text(
            region_match.group(1)
        )

        if region:
            return region

    return "Remote"


def extract_fallback_salary(
    visible_text,
):
    text = re.sub(
        r"\s+",
        " ",
        visible_text or "",
    )

    salary_match = re.search(
        r"\bSalary\s+"
        r"(.{1,100}?)"
        r"(?=\s+(?:Category|"
        r"Region|"
        r"Apply now|"
        r"Related Jobs)|$)",
        text,
        flags=re.IGNORECASE,
    )

    if not salary_match:
        return None

    salary = clean_html_text(
        salary_match.group(1)
    )

    if not salary:
        return None

    rejected_values = {
        "not specified",
        "unspecified",
        "competitive",
    }

    if salary.lower() in rejected_values:
        return None

    return salary


def extract_fallback_description(
    visible_text,
    position_title,
):
    text = visible_text or ""

    if not text:
        return None

    title_pattern = re.escape(
        position_title
    )

    title_matches = list(
        re.finditer(
            title_pattern,
            text,
            flags=re.IGNORECASE,
        )
    )

    # WWR commonly prints the title once in navigation
    # and then again immediately before the real description.
    if len(title_matches) >= 2:
        description_start = (
            title_matches[1].end()
        )
    elif title_matches:
        description_start = (
            title_matches[0].end()
        )
    else:
        description_start = 0

    ending_patterns = [
        r"\nAbout the job\b",
        r"\nRelated Jobs\b",
        r"\nAbout the company\b",
        r"\nView company\b",
    ]

    description_end = len(text)

    remaining_text = text[
        description_start:
    ]

    for ending_pattern in ending_patterns:
        ending_match = re.search(
            ending_pattern,
            remaining_text,
            flags=re.IGNORECASE,
        )

        if ending_match:
            candidate_end = (
                description_start
                + ending_match.start()
            )

            description_end = min(
                description_end,
                candidate_end,
            )

    description = text[
        description_start:
        description_end
    ]

    description = re.sub(
        r"^\s*Remote Opportunity\s*",
        "",
        description,
        flags=re.IGNORECASE,
    )

    description = re.sub(
        r"\n{3,}",
        "\n\n",
        description,
    ).strip()

    if len(description) < 100:
        return None

    return description


def is_recent_datetime(
    value,
    max_age_days,
):
    published_at = parse_datetime(
        value
    )

    if published_at is None:
        return False

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=max_age_days)
    )

    return published_at >= cutoff


def extract_company_name(job_posting):
    hiring_organization = job_posting.get(
        "hiringOrganization"
    )

    if isinstance(
        hiring_organization,
        dict,
    ):
        company_name = hiring_organization.get(
            "name"
        )

        if company_name:
            return clean_html_text(
                company_name
            )

    return "Unknown Company"


def extract_location_parts(value):
    results = []

    if isinstance(value, str):
        cleaned_value = clean_html_text(
            value
        )

        if cleaned_value:
            results.append(
                cleaned_value
            )

        return results

    if isinstance(value, list):
        for item in value:
            results.extend(
                extract_location_parts(
                    item
                )
            )

        return results

    if not isinstance(value, dict):
        return results

    name = clean_html_text(
        value.get("name")
    )

    if name:
        results.append(name)

    address = value.get("address")

    if isinstance(address, dict):
        address_parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]

        address_text = ", ".join(
            str(part).strip()
            for part in address_parts
            if part
        )

        if address_text:
            results.append(
                address_text
            )

    return results


def unique_values(values):
    results = []

    for value in values:
        normalized_value = clean_html_text(
            value
        )

        if not normalized_value:
            continue

        if normalized_value not in results:
            results.append(
                normalized_value
            )

    return results


def extract_location(job_posting):
    applicant_locations = extract_location_parts(
        job_posting.get(
            "applicantLocationRequirements"
        )
    )

    explicit_locations = extract_location_parts(
        job_posting.get(
            "jobLocation"
        )
    )

    combined_locations = unique_values(
        applicant_locations
        + explicit_locations
    )

    # WWR/We Work Remotely sometimes represents worldwide availability
    # by listing nearly every ISO country code.
    short_country_codes = {
        location.upper()
        for location in combined_locations
        if re.fullmatch(
            r"[A-Za-z]{2}",
            location.strip(),
        )
    }

    if len(short_country_codes) >= 100:
        return "Worldwide"

    if combined_locations:
        return " | ".join(
            combined_locations
        )

    job_location_type = normalize_text(
        job_posting.get(
            "jobLocationType"
        )
    )

    if "telecommute" in job_location_type:
        return "Worldwide"

    return "Remote"


def normalize_employment_type(value):
    if isinstance(value, list):
        value = (
            value[0]
            if value
            else None
        )

    text = normalize_text(
        value
    )

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
        text,
        clean_html_text(value)
        or "Full-time",
    )


def extract_salary(job_posting):
    base_salary = job_posting.get(
        "baseSalary"
    )

    if not isinstance(base_salary, dict):
        return None

    currency = (
        base_salary.get("currency")
        or "USD"
    )

    value = base_salary.get(
        "value"
    )

    if isinstance(value, dict):
        minimum_value = value.get(
            "minValue"
        )

        maximum_value = value.get(
            "maxValue"
        )

        unit_text = value.get(
            "unitText"
        )

        if (
            minimum_value is not None
            and maximum_value is not None
        ):
            salary_text = (
                f"{currency} "
                f"{minimum_value} - "
                f"{maximum_value}"
            )
        elif minimum_value is not None:
            salary_text = (
                f"{currency} "
                f"from {minimum_value}"
            )
        elif maximum_value is not None:
            salary_text = (
                f"{currency} "
                f"up to {maximum_value}"
            )
        else:
            return None

        if unit_text:
            salary_text += (
                f" per "
                f"{str(unit_text).lower()}"
            )

        return salary_text

    if value is not None:
        return (
            f"{currency} {value}"
        )

    return None


def create_external_id(url):
    path = urlparse(
        url
    ).path.rstrip("/")

    return path.split("/")[-1]


def normalize_wwr_html_fallback(
    html,
    url,
    max_age_days,
):
    page_title = extract_page_title(
        html
    )

    company_name, position_title = (
        split_wwr_page_title(
            page_title
        )
    )

    visible_text = extract_visible_text(
        html
    )

    published_at = (
        extract_relative_posted_date(
            visible_text
        )
    )

    if published_at is None:
        print(
            f"WWR FALLBACK REJECTED | "
            f"No usable posting date | "
            f"Title: {position_title} | "
            f"URL: {url}"
        )
        return None

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(
            days=max_age_days
        )
    )

    if published_at < cutoff:
        print(
            f"WWR FALLBACK TOO OLD | "
            f"Date: {published_at} | "
            f"Title: {position_title} | "
            f"URL: {url}"
        )
        return None

    description = (
        extract_fallback_description(
            visible_text,
            position_title,
        )
    )

    if not description:
        print(
            f"WWR FALLBACK REJECTED | "
            f"No usable description | "
            f"Title: {position_title} | "
            f"URL: {url}"
        )
        return None

    location = extract_fallback_location(
        visible_text
    )

    employment_type = (
        extract_fallback_employment_type(
            visible_text
        )
    )

    salary = extract_fallback_salary(
        visible_text
    )

    return {
        "source": "We Work Remotely",
        "external_id": create_external_id(
            url
        ),
        "company_name": company_name,
        "position_title": position_title,
        "location": location,
        "employment_type": (
            employment_type
        ),
        "salary": salary,
        "visa_sponsorship": "unknown",
        "posting_url": url,
        "apply_url": url,
        "job_description": description,
        "departments": [],
        "offices": [],
        "is_remote": True,
        "workplace_type": "Remote",
        "published_at": published_at,
        "recruiter_name": None,
        "recruiter_email": None,
        "recruiter_contact_url": None,
        "recruiter_contact_source": None,
    }


def fetch_and_normalize_wwr_job(
    url,
    max_age_days=MAX_JOB_AGE_DAYS,
):
    html = fetch_html(
        url,
        timeout=60,
    )

    job_posting = (
        find_job_posting_json_ld(
            html
        )
    )

    if not job_posting:
        fallback_job = (
            normalize_wwr_html_fallback(
                html=html,
                url=url,
                max_age_days=max_age_days,
            )
        )

        if fallback_job:
            print(
                f"WWR HTML FALLBACK SUCCESS | "
                f"Title: "
                f"{fallback_job.get('position_title')} | "
                f"Company: "
                f"{fallback_job.get('company_name')} | "
                f"Location: "
                f"{fallback_job.get('location')} | "
                f"Salary: "
                f"{fallback_job.get('salary') or 'unknown'}"
            )

        return fallback_job

    published_value = job_posting.get(
        "datePosted"
    )

    if not published_value:
        print(
            f"WWR PAGE REJECTED | "
            f"No datePosted: {url}"
        )
        return None

    published_at = parse_datetime(
        published_value
    )

    if published_at is None:
        print(
            f"WWR PAGE REJECTED | "
            f"Unparseable date: "
            f"{published_value} | "
            f"URL: {url}"
        )
        return None

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=max_age_days)
    )

    if published_at < cutoff:
        print(
            f"WWR PAGE TOO OLD | "
            f"Date: {published_at} | "
            f"URL: {url}"
        )
        return None

    title = clean_html_text(
        job_posting.get("title")
    )

    company_name = extract_company_name(
        job_posting
    )

    description = clean_html_text(
        job_posting.get(
            "description"
        )
    )

    location = extract_location(
        job_posting
    )

    employment_type = (
        normalize_employment_type(
            job_posting.get(
                "employmentType"
            )
        )
    )

    return {
        "source": "We Work Remotely",
        "external_id": create_external_id(
            url
        ),
        "company_name": (
            company_name
            or "Unknown Company"
        ),
        "position_title": (
            title
            or "Untitled Position"
        ),
        "location": location,
        "employment_type": (
            employment_type
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
        "recruiter_name": None,
        "recruiter_email": None,
        "recruiter_contact_url": None,
        "recruiter_contact_source": None,
    }


def crawl_recent_wwr_jobs(
    profile,
    excluded_urls=None,
    max_age_days=MAX_JOB_AGE_DAYS,
    max_job_pages=MAX_JOB_PAGES_PER_RUN,
):
    discovered_entries = (
        discover_wwr_job_urls(
            profile=profile,
            excluded_urls=excluded_urls,
            max_job_urls=max_job_pages,
        )
    )

    normalized_jobs = []

    for index, entry in enumerate(
        discovered_entries,
        start=1,
    ):
        url = entry["url"]

        print(
            f"WWR CRAWL PAGE "
            f"{index}/"
            f"{len(discovered_entries)}: "
            f"{url}"
        )

        try:
            job = fetch_and_normalize_wwr_job(
                url=url,
                max_age_days=max_age_days,
            )

            if job:
                normalized_jobs.append(job)

                print(
                    f"WWR NORMALIZED JOB | "
                    f"Title: "
                    f"{job.get('position_title')} | "
                    f"Company: "
                    f"{job.get('company_name')} | "
                    f"Location: "
                    f"{job.get('location')} | "
                    f"Published: "
                    f"{job.get('published_at')}"
                )

        except Exception as error:
            print(
                f"WWR CRAWL ERROR | "
                f"URL: {url} | "
                f"Error: {error}"
            )

        time.sleep(
            REQUEST_DELAY_SECONDS
        )

    print(
        f"WWR CRAWL COMPLETE | "
        f"Discovered candidates: "
        f"{len(discovered_entries)} | "
        f"Normalized recent jobs: "
        f"{len(normalized_jobs)}"
    )

    return normalized_jobs
