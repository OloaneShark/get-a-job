
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

EXPERIENCE_URL_TERMS = {
    "intern": {
        "intern",
        "internship",
    },
    "entry": {
        "entry",
        "entry level",
        "graduate",
        "new grad",
        "new graduate",
    },
    "junior": {
        "junior",
        "jr",
    },
    "mid": {
        "mid",
        "mid level",
        "intermediate",
    },
    "senior": {
        "senior",
        "sr",
    },
    "staff": {
        "staff",
    },
    "principal": {
        "principal",
    },
    "lead": {
        "lead",
        "tech lead",
        "technical lead",
    },
    "manager": {
        "manager",
        "director",
        "head",
        "vp",
        "vice president",
    },
}

BROAD_PROFILE_TERMS = {
    "administrator", "associate", "developer", "engineer",
    "entry", "graduate", "intern", "internship", "it",
    "junior", "software", "systems", "support",
    "technician", "web",
}

TECHNICAL_ROLE_PATTERNS = (
    r"\b(?:full[\s-]?stack|backend|back[\s-]?end|frontend|front[\s-]?end)"
    r"\s+(?:developer|engineer)\b",
    r"\b(?:software|web|python|cloud|platform|infrastructure|systems?)"
    r"\s+(?:developer|engineer|administrator)\b",
    r"\bdevsecops\b",
    r"\bdevops(?:\s+engineer)?\b",
    r"\b(?:help|service)\s+desk\b",
    r"\b(?:desktop|technical|cloud|it)\s+support\b",
    r"\bit\s+(?:specialist|technician|analyst|administrator)\b",
    r"\bsystems?\s+administrator\b",
)

FALLBACK_METADATA_LABELS = {
    "category",
    "company",
    "employment type",
    "job type",
    "location",
    "region",
    "salary",
}

LOCATION_CONFIDENCE = {
    "json_ld": 0.95,
    "metadata": 0.85,
    "fallback_remote": 0.35,
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


def canonical_wwr_job_key(url):
    normalized_url = normalize_posting_url(url)

    if not normalized_url:
        return None

    slug = (
        urlparse(normalized_url)
        .path.rstrip("/")
        .split("/")[-1]
        .lower()
    )

    return re.sub(
        r"-\d+$",
        "",
        slug,
    )


def profile_role_phrases(profile):
    phrases = []

    for keyword in parse_profile_keywords(profile):
        phrase = normalize_text(
            keyword.replace("-", " ")
        )

        if not phrase:
            continue

        if phrase in BROAD_PROFILE_TERMS:
            continue

        if (
            len(phrase.split()) == 1
            and phrase in {
                "admin", "ai", "cloud", "it",
                "systems", "support",
            }
        ):
            continue

        if phrase not in phrases:
            phrases.append(phrase)

    return phrases


def title_has_technical_role(
    readable_slug,
    profile,
):
    matched_phrases = [
        phrase
        for phrase in profile_role_phrases(profile)
        if contains_url_term(
            readable_slug,
            phrase,
        )
    ]

    pattern_match = any(
        re.search(
            pattern,
            readable_slug,
            flags=re.IGNORECASE,
        )
        for pattern in TECHNICAL_ROLE_PATTERNS
    )

    return (
        bool(matched_phrases)
        or pattern_match,
        matched_phrases,
    )


def parse_profile_values(value):
    if not value:
        return []

    return [
        item.strip().lower()
        for item in re.split(
            r"[\n,]+",
            str(value),
        )
        if item.strip()
    ]


def get_requested_experience_levels(
    profile,
):
    return set(
        parse_profile_values(
            getattr(
                profile,
                "experience_levels",
                None,
            )
        )
    )


def detect_url_experience_levels(
    readable_slug,
):
    detected_levels = set()

    for level, terms in (
        EXPERIENCE_URL_TERMS.items()
    ):
        if any(
            contains_url_term(
                readable_slug,
                term,
            )
            for term in terms
        ):
            detected_levels.add(level)

    if not detected_levels:
        detected_levels.add(
            "unspecified"
        )

    return detected_levels


def url_experience_is_allowed(
    readable_slug,
    profile,
):
    requested_levels = (
        get_requested_experience_levels(
            profile
        )
    )

    # No selected experience filters means all
    # levels are allowed.
    if not requested_levels:
        return True, {
            "unspecified",
        }

    detected_levels = (
        detect_url_experience_levels(
            readable_slug
        )
    )

    if "unspecified" in detected_levels:
        return (
            "unspecified"
            in requested_levels,
            detected_levels,
        )

    return (
        bool(
            requested_levels.intersection(
                detected_levels
            )
        ),
        detected_levels,
    )


def url_keyword_score(
    url,
    profile,
):
    raw_slug = (
        urlparse(url)
        .path.replace(
            "/remote-jobs/",
            "",
        )
        .strip("/")
        .lower()
    )

    readable_slug = normalize_text(
        raw_slug.replace("-", " ")
    )

    role_match, matched_phrases = (
        title_has_technical_role(
            readable_slug,
            profile,
        )
    )
    
    experience_allowed, detected_levels = (
        url_experience_is_allowed(
            readable_slug,
            profile,
        )
    )

    if not role_match:
        return {
            "score": 0,
            "role_match": False,
            "experience_allowed": False,
            "detected_levels": (
                detected_levels
            ),
            "matched_phrases": [],
            "readable_slug": readable_slug,
        }

    if not experience_allowed:
        return {
            "score": 0,
            "role_match": True,
            "experience_allowed": False,
            "detected_levels": (
                detected_levels
            ),
            "matched_phrases": (
                matched_phrases
            ),
            "readable_slug": readable_slug,
        }

    score = 10

    for phrase in matched_phrases:
        score += max(
            4,
            len(phrase.split()) * 3,
        )

    for term, adjustment in ENTRY_LEVEL_URL_TERMS.items():
        readable_term = term.replace("-", " ")

        if (
            term in raw_slug
            or contains_url_term(
                readable_slug,
                readable_term,
            )
        ):
            score += adjustment

    for term, adjustment in SENIOR_URL_TERMS.items():
        if contains_url_term(
            readable_slug,
            term,
        ):
            score += adjustment

    return {
        "score": score,
        "role_match": True,
        "experience_allowed": True,
        "detected_levels": detected_levels,
        "matched_phrases": matched_phrases,
        "readable_slug": readable_slug,
    }


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

    excluded_keys = {
        canonical_wwr_job_key(url)
        for url in excluded_urls
        if canonical_wwr_job_key(url)
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

    discovered_by_key = {}
    duplicate_count = 0
    excluded_count = 0
    non_role_count = 0
    experience_rejected_count = 0

    for href in parser.links:
        normalized_url = normalize_posting_url(
            href
        )

        if not normalized_url:
            continue

        canonical_key = canonical_wwr_job_key(
            normalized_url
        )

        if not canonical_key:
            continue

        if (
            normalized_url in excluded_urls
            or canonical_key in excluded_keys
        ):
            excluded_count += 1
            continue

        details = url_keyword_score(
            normalized_url,
            profile,
        )

        if not details["role_match"]:
            non_role_count += 1
            continue
        
        if not details[
            "experience_allowed"
        ]:
            experience_rejected_count += 1
            continue

        candidate = {
            "url": normalized_url,
            "canonical_key": canonical_key,
            "keyword_score": details["score"],
            "matched_phrases": details[
                "matched_phrases"
            ],
            "readable_slug": details[
                "readable_slug"
            ],
            "detected_levels": details[
                "detected_levels"
            ],
        }

        existing = discovered_by_key.get(
            canonical_key
        )

        if existing is None:
            discovered_by_key[
                canonical_key
            ] = candidate
            continue

        duplicate_count += 1

        candidate_rank = (
            candidate["keyword_score"],
            -len(candidate["url"]),
            candidate["url"],
        )
        existing_rank = (
            existing["keyword_score"],
            -len(existing["url"]),
            existing["url"],
        )

        if candidate_rank > existing_rank:
            discovered_by_key[
                canonical_key
            ] = candidate

    ranked_urls = list(
        discovered_by_key.values()
    )

    ranked_urls.sort(
        key=lambda entry: (
            entry["keyword_score"],
            -len(entry["url"]),
            entry["url"],
        ),
        reverse=True,
    )

    selected_urls = ranked_urls[
        :max_job_urls
    ]

    print(
        f"WWR LISTING DISCOVERY | "
        f"Qualified unique roles: "
        f"{len(ranked_urls)} | "
        f"Duplicates removed: "
        f"{duplicate_count} | "
        f"Non-role URLs rejected: "
        f"{non_role_count} | "
        f"Experience rejected: "
        f"{experience_rejected_count} | "
        f"Excluded: {excluded_count} | "
        f"Selected: {len(selected_urls)} | "
        f"Page limit: {max_job_urls}"
    )

    for entry in selected_urls:
        matched_text = (
            ", ".join(
                entry["matched_phrases"]
            )
            or "technical role pattern"
        )

        print(
            f"WWR CANDIDATE SELECTED | "
            f"Score: "
            f"{entry['keyword_score']} | "
            f"Matched: {matched_text} | "
            f"Key: "
            f"{entry['canonical_key']} | "
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


def extract_fallback_metadata_value(
    visible_text,
    label,
):
    if not visible_text:
        return None

    lines = [
        re.sub(
            r"\s+",
            " ",
            line,
        ).strip()
        for line in str(
            visible_text
        ).splitlines()
    ]

    lines = [
        line
        for line in lines
        if line
    ]

    normalized_label = normalize_text(
        label
    )

    for index, line in enumerate(
        lines
    ):
        normalized_line = normalize_text(
            line
        )

        # Format:
        # Region
        # USA Only
        if normalized_line == normalized_label:
            if index + 1 >= len(lines):
                return None

            candidate = lines[
                index + 1
            ].strip()

            if (
                normalize_text(candidate)
                in FALLBACK_METADATA_LABELS
            ):
                return None

            return candidate

        # Format:
        # Region: USA Only
        prefix_patterns = [
            f"{normalized_label}:",
            f"{normalized_label} -",
        ]

        for prefix in prefix_patterns:
            if not normalized_line.startswith(
                prefix
            ):
                continue

            candidate = line[
                len(prefix):
            ].strip()

            if candidate:
                return candidate

    return None


def normalize_fallback_region(
    value,
):
    region = clean_html_text(
        value
    )

    if not region:
        return None

    region = re.sub(
        r"\s+",
        " ",
        region,
    ).strip()

    normalized_region = normalize_text(
        region
    )

    worldwide_values = {
        "anywhere",
        "anywhere in the world",
        "global",
        "global remote",
        "remote worldwide",
        "worldwide",
    }

    united_states_values = {
        "america only",
        "north america",
        "us",
        "u.s.",
        "u.s. only",
        "usa",
        "usa only",
        "united states",
        "united states only",
    }

    if normalized_region in worldwide_values:
        return "Worldwide"

    if normalized_region in united_states_values:
        return "United States"

    replacements = {
        "americas only": "Americas",
        "europe only": "Europe",
        "european only": "Europe",
        "emea only": "EMEA",
        "latin america only": "Latin America",
        "latam only": "Latin America",
        "uk only": "United Kingdom",
        "united kingdom only": (
            "United Kingdom"
        ),
        "canada only": "Canada",
    }

    return replacements.get(
        normalized_region,
        region,
    )


def extract_fallback_employment_type(
    visible_text,
):
    employment_value = (
        extract_fallback_metadata_value(
            visible_text,
            "Job Type",
        )
        or extract_fallback_metadata_value(
            visible_text,
            "Employment Type",
        )
    )

    if employment_value:
        return normalize_employment_type(
            employment_value
        )

    text = normalize_text(
        visible_text
    )

    patterns = [
        (
            r"\bfull[-\s]?time\b",
            "Full-time",
        ),
        (
            r"\bpart[-\s]?time\b",
            "Part-time",
        ),
        (
            r"\bcontract(?:or)?\b",
            "Contract",
        ),
        (
            r"\btemporary\b",
            "Temporary",
        ),
        (
            r"\binternship\b",
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
    region_value = (
        extract_fallback_metadata_value(
            visible_text,
            "Region",
        )
    )

    location_value = (
        extract_fallback_metadata_value(
            visible_text,
            "Location",
        )
    )

    raw_value = (
        region_value
        or location_value
    )

    normalized_region = (
        normalize_fallback_region(
            raw_value
        )
    )

    if normalized_region:
        return {
            "value": normalized_region,
            "raw_value": raw_value,
            "source": "wwr_metadata",
            "confidence": (
                LOCATION_CONFIDENCE[
                    "metadata"
                ]
            ),
        }

    return {
        "value": "Remote",
        "raw_value": None,
        "source": "fallback_default",
        "confidence": (
            LOCATION_CONFIDENCE[
                "fallback_remote"
            ]
        ),
    }


def extract_fallback_salary(
    visible_text,
):
    salary = (
        extract_fallback_metadata_value(
            visible_text,
            "Salary",
        )
    )

    if not salary:
        return None

    salary = clean_html_text(
        salary
    )

    if not salary:
        return None

    rejected_values = {
        "-",
        "competitive",
        "not provided",
        "not specified",
        "n/a",
        "none",
        "unspecified",
    }

    if normalize_text(
        salary
    ) in rejected_values:
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

    location_result = (
        extract_fallback_location(
            visible_text
        )
    )

    print(
        f"WWR LOCATION METADATA | "
        f"Title: {position_title} | "
        f"Raw: "
        f"{location_result.get('raw_value')} | "
        f"Normalized: "
        f"{location_result.get('value')} | "
        f"Source: "
        f"{location_result.get('source')} | "
        f"Confidence: "
        f"{location_result.get('confidence')}"
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
        "location": (
            location_result.get("value")
        ),
        "location_raw": (
            location_result.get("raw_value")
        ),
        "location_source": (
            location_result.get("source")
        ),
        "location_confidence": (
            location_result.get(
                "confidence"
            )
        ),
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
    
    location_source = (
        "jobposting_json_ld"
    )

    location_confidence = (
        LOCATION_CONFIDENCE[
            "json_ld"
        ]
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
        "location_raw": location,
        "location_source": (
            location_source
        ),
        "location_confidence": (
            location_confidence
        ),
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
