
import os
import re
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from contextvars import ContextVar



JOB_MATCH_DEBUG = os.getenv(
    "JOB_MATCH_DEBUG",
    "false",
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


_ACTIVE_MATCH_DIAGNOSTICS = ContextVar(
    "active_match_diagnostics",
    default=None,
)


def create_match_diagnostics():
    return {
        "evaluated": 0,
        "matched": 0,
        "rejected": 0,
        "multiple_failures": 0,
        "failures": {
            "role": 0,
            "experience": 0,
            "location": 0,
            "workplace_type": 0,
            "employment_type": 0,
            "visa": 0,
            "overseas": 0,
            "posting_age": 0,
        },
    }


@contextmanager
def collect_match_diagnostics():
    diagnostics = create_match_diagnostics()
    token = _ACTIVE_MATCH_DIAGNOSTICS.set(
        diagnostics
    )

    try:
        yield diagnostics
    finally:
        _ACTIVE_MATCH_DIAGNOSTICS.reset(
            token
        )


def record_match_diagnostics(
    matched,
    failed_checks,
):
    diagnostics = (
        _ACTIVE_MATCH_DIAGNOSTICS.get()
    )

    if diagnostics is None:
        return

    diagnostics["evaluated"] += 1

    if matched:
        diagnostics["matched"] += 1
        return

    diagnostics["rejected"] += 1

    if len(failed_checks) > 1:
        diagnostics[
            "multiple_failures"
        ] += 1

    for failed_check in failed_checks:
        if failed_check in diagnostics[
            "failures"
        ]:
            diagnostics["failures"][
                failed_check
            ] += 1


def format_match_diagnostics(
    profile_name,
    source_name,
    diagnostics,
):
    failures = diagnostics["failures"]

    return (
        f"JOB FILTER SUMMARY | "
        f"Profile: {profile_name} | "
        f"Source: {source_name} | "
        f"Evaluated: "
        f"{diagnostics['evaluated']} | "
        f"Matched: "
        f"{diagnostics['matched']} | "
        f"Rejected: "
        f"{diagnostics['rejected']} | "
        f"Role: {failures['role']} | "
        f"Experience: "
        f"{failures['experience']} | "
        f"Location: "
        f"{failures['location']} | "
        f"Workplace type: "
        f"{failures['workplace_type']} | "
        f"Employment type: "
        f"{failures['employment_type']} | "
        f"Visa: {failures['visa']} | "
        f"Overseas: {failures['overseas']} | "
        f"Posting age: {failures['posting_age']} | "
        f"Multiple failures: "
        f"{diagnostics['multiple_failures']}"
    )


TECHNICAL_TITLE_TERMS = {
    "software engineer",
    "software developer",
    "developer",
    "frontend",
    "front end",
    "front-end",
    "backend",
    "back end",
    "back-end",
    "fullstack",
    "full stack",
    "full-stack",
    "devops",
    "devsecops",
    "cloud engineer",
    "security engineer",
    "application security",
    "cybersecurity",
    "site reliability",
    "sre",
    "platform engineer",
    "qa engineer",
    "quality assurance engineer",
    "data engineer",
    "machine learning engineer",
    "mobile developer",
    "web developer",
    "python developer",
}


EXCLUDED_TITLE_TERMS = {
    "account executive",
    "account manager",
    "business development",
    "customer success",
    "data entry",
    "human resources",
    "hr specialist",
    "immigration lawyer",
    "lawyer",
    "legal counsel",
    "lifecycle specialist",
    "marketing",
    "mobility specialist",
    "product manager",
    "project manager",
    "recruiter",
    "recruiting",
    "sales",
    "sales development",
}


EXPERIENCE_TERMS = {
    "intern": {
        "intern",
        "internship",
        "co-op",
        "coop",
        "student",
    },
    "entry": {
        "entry",
        "entry level",
        "entry-level",
        "graduate",
        "new grad",
        "new graduate",
        "associate",
    },
    "junior": {
        "junior",
        "jr.",
        "jr ",
    },
    "mid": {
        "mid",
        "mid level",
        "mid-level",
        "intermediate",
    },
    "senior": {
        "senior",
        "sr.",
        "sr ",
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
        "head of",
        "vice president",
        "vp ",
    },
}


EXPERIENCE_YEAR_PATTERNS = [
    re.compile(
        r"\b"
        r"(?:minimum(?:\s+of)?|at\s+least|over|more\s+than)?"
        r"\s*"
        r"(\d{1,2})"
        r"\s*(?:\+|plus)?"
        r"\s*(?:years?|yrs?)"
        r"\s+(?:of\s+)?"
        r"(?:professional\s+|relevant\s+|commercial\s+|"
        r"industry\s+|hands[-\s]?on\s+)?"
        r"experience\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b"
        r"(?:professional\s+|relevant\s+|commercial\s+|"
        r"industry\s+|hands[-\s]?on\s+)?"
        r"experience"
        r"(?:\s+of|\s*:)?"
        r"\s*"
        r"(\d{1,2})"
        r"\s*(?:\+|plus)?"
        r"\s*(?:years?|yrs?)\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b"
        r"(?:minimum(?:\s+of)?|at\s+least|over|more\s+than)?"
        r"\s*"
        r"(\d{1,2})"
        r"\s*(?:\+|plus)?"
        r"\s*(?:years?|yrs?)"
        r"\s+(?:of\s+)?"
        r"(?:building|developing|engineering|programming|"
        r"working|designing|implementing|maintaining|"
        r"creating|writing)"
        r"\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b"
        r"(\d{1,2})"
        r"\s*(?:-|–|—|to)"
        r"\s*\d{1,2}"
        r"\s*(?:years?|yrs?)"
        r"(?:\s+of)?"
        r"(?:\s+\w+){0,5}?"
        r"\s+experience\b",
        re.IGNORECASE,
    ),
]


VISA_POSITIVE_TERMS = {
    "visa sponsorship available",
    "visa sponsorship provided",
    "visa sponsorship offered",
    "sponsorship available",
    "sponsor visas",
    "sponsors visas",
    "work visa support",
    "relocation and visa",
    "visa support",
}


VISA_NEGATIVE_TERMS = {
    "no visa sponsorship",
    "unable to sponsor",
    "cannot sponsor",
    "can't sponsor",
    "will not sponsor",
    "not eligible for sponsorship",
    "must be authorized to work",
    "without sponsorship",
    "no sponsorship available",
}


REMOTE_TERMS = {
    "remote",
    "fully remote",
    "work from home",
    "distributed",
}


GENERIC_KEYWORDS = {
    "full",
    "stack",
    "entry",
    "junior",
    "mid",
    "senior",
    "intern",
    "internship",
}


ROLE_FAMILY_ALIASES = {
    "full stack": {
        "full stack",
        "fullstack",
        "frontend",
        "front end",
        "backend",
        "back end",
    },
    "frontend": {
        "frontend",
        "front end",
    },
    "backend": {
        "backend",
        "back end",
    },
}


BROAD_ROLE_KEYWORDS = {
    "administrator",
    "systems",
}


# Some boards put a secondary skill in the title, for example:
# "Data Engineering with knowledge in DevOps". Text after one of
# these qualifiers describes supporting knowledge, not the core role.
SECONDARY_ROLE_QUALIFIER_PATTERNS = (
    re.compile(
        r"\b(?:with|com)\s+"
        r"(?:knowledge|conhecimento|experience|experiencia|experiência)"
        r"\s+(?:in|em|of|with|com)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:knowledge|conhecimento|familiarity|familiaridade)"
        r"\s+(?:in|em|of|with|com)\b",
        re.IGNORECASE,
    ),
)


# Marketplace/network listings can omit a normal seniority field while
# still explicitly positioning applicants as top expert freelancers.
# Treat that language as senior-level rather than "unspecified".
EXPERT_LEVEL_DESCRIPTION_PHRASES = {
    "exclusive network of the top",
    "top freelance software developers",
    "top freelance developers",
    "top 3% of freelance talent",
    "top 3% of talent",
    "verified expert in engineering",
}


ALLOWED_ADMINISTRATOR_PATTERNS = {
    "cloud administrator",
    "database administrator",
    "it administrator",
    "linux administrator",
    "network administrator",
    "security administrator",
    "system administrator",
    "systems administrator",
    "windows administrator",
}


LOCATION_ALIASES = {
    "united states": {
        "united states",
        "united states of america",
        "usa",
        "u.s.a.",
        "us",
        "u.s.",
    },
    "canada": {
        "canada",
        "canadian",
    },
    "japan": {
        "japan",
        "japanese",
        "tokyo",
    },
}


US_STATE_NAMES = {
    "alabama",
    "alaska",
    "arizona",
    "arkansas",
    "california",
    "colorado",
    "connecticut",
    "delaware",
    "florida",
    "georgia",
    "hawaii",
    "idaho",
    "illinois",
    "indiana",
    "iowa",
    "kansas",
    "kentucky",
    "louisiana",
    "maine",
    "maryland",
    "massachusetts",
    "michigan",
    "minnesota",
    "mississippi",
    "missouri",
    "montana",
    "nebraska",
    "nevada",
    "new hampshire",
    "new jersey",
    "new mexico",
    "new york",
    "north carolina",
    "north dakota",
    "ohio",
    "oklahoma",
    "oregon",
    "pennsylvania",
    "rhode island",
    "south carolina",
    "south dakota",
    "tennessee",
    "texas",
    "utah",
    "vermont",
    "virginia",
    "washington",
    "west virginia",
    "wisconsin",
    "wyoming",
    "district of columbia",
}


US_STATE_ABBREVIATIONS = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}


WORLDWIDE_REMOTE_TERMS = {
    "worldwide",
    "anywhere",
    "global",
    "remote worldwide",
}


def parse_profile_values(value):
    if not value:
        return []

    return [
        item.strip().lower()
        for item in re.split(r"[\n,]+", value)
        if item.strip()
    ]


def normalize_text(value):
    text = str(value or "").strip().lower()

    text = re.sub(
        r"(?<=\w)-(?=\w)",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    )


def normalize_role_phrase(value):
    return normalize_text(value)


def get_core_role_title(value):
    title = normalize_role_phrase(value)

    if not title:
        return ""

    qualifier_positions = []

    for pattern in SECONDARY_ROLE_QUALIFIER_PATTERNS:
        match = pattern.search(title)

        if match:
            qualifier_positions.append(match.start())

    if qualifier_positions:
        title = title[:min(qualifier_positions)]

    return title.strip(" -–—|:/,()")


def get_implied_experience_levels(job):
    searchable_text = normalize_text(
        " ".join([
            job.get("company_name") or "",
            job.get("position_title") or "",
            job.get("job_description") or "",
        ])
    )

    if any(
        phrase in searchable_text
        for phrase in EXPERT_LEVEL_DESCRIPTION_PHRASES
    ):
        return {"senior"}

    return set()


def get_profile_role_families(profile):
    keywords = {
        normalize_role_phrase(keyword)
        for keyword in parse_profile_values(
            profile.keywords
        )
    }

    families = set()

    if keywords.intersection(
        {
            "full stack",
            "fullstack",
        }
    ):
        families.add("full stack")

    if keywords.intersection(
        {
            "frontend",
            "front end",
        }
    ):
        families.add("frontend")

    if keywords.intersection(
        {
            "backend",
            "back end",
        }
    ):
        families.add("backend")

    return families


def title_matches_role_family(
    title,
    family,
):
    aliases = ROLE_FAMILY_ALIASES.get(
        family,
        set(),
    )

    return any(
        contains_phrase(
            title,
            normalize_role_phrase(alias),
        )
        for alias in aliases
    )


def expand_location_aliases(locations):
    expanded = set()

    for location in locations:
        normalized_location = normalize_text(
            location
        )

        expanded.add(normalized_location)

        for canonical_location, aliases in (
            LOCATION_ALIASES.items()
        ):
            if normalized_location in aliases:
                expanded.add(canonical_location)
                expanded.update(aliases)

    return expanded


def contains_phrase(text, phrase):
    pattern = (
        r"(?<!\w)"
        + re.escape(phrase)
        + r"(?!\w)"
    )

    return bool(re.search(pattern, text))


def location_is_united_states(location):
    location = normalize_text(location)

    if not location:
        return False

    direct_us_terms = {
        "united states",
        "united states of america",
        "usa",
        "u.s.a.",
        "u.s.",
    }

    if any(
        contains_phrase(location, term)
        for term in direct_us_terms
    ):
        return True

    if any(
        contains_phrase(location, state)
        for state in US_STATE_NAMES
    ):
        return True

    abbreviation_matches = re.findall(
        r"(?:^|[\s,()/\-])"
        r"([a-z]{2})"
        r"(?=$|[\s,()/\-])",
        location
    )

    return any(
        abbreviation
        in US_STATE_ABBREVIATIONS
        for abbreviation
        in abbreviation_matches
    )


def get_requested_experience_levels(profile):
    value = getattr(
        profile,
        "experience_levels",
        None
    )

    return set(parse_profile_values(value))


def normalize_structured_experience_level(value):
    normalized = normalize_text(value)

    mappings = {
        "intern": "intern",
        "internship": "intern",
        "student": "intern",
        "entry": "entry",
        "entry level": "entry",
        "new grad": "entry",
        "new graduate": "entry",
        "graduate": "entry",
        "new grad or above": "entry",
        "junior": "junior",
        "jr": "junior",
        "junior level": "junior",
        "junior or above": "junior",
        "mid": "mid",
        "mid level": "mid",
        "middle": "mid",
        "intermediate": "mid",
        "mid level or above": "mid",
        "senior": "senior",
        "senior level": "senior",
        "sr": "senior",
        "staff": "staff",
        "staff level": "staff",
        "principal": "principal",
        "principal level": "principal",
        "lead": "lead",
        "tech lead": "lead",
        "technical lead": "lead",
        "manager": "manager",
        "engineering manager": "manager",
        "director": "manager",
        "head": "manager",
    }

    return mappings.get(normalized)


def get_structured_experience_levels(job):
    levels = set()

    for field_name in (
        "experience_level",
        "seniority_level",
        "seniority",
    ):
        raw_value = job.get(field_name)

        if isinstance(raw_value, (list, tuple, set)):
            values = raw_value
        else:
            values = [raw_value]

        for value in values:
            level = normalize_structured_experience_level(value)

            if level:
                levels.add(level)

    return levels


def get_structured_experience_level(job):
    # Compatibility wrapper for any older caller that still expects
    # one level. Multi-level source data is handled by the plural helper.
    levels = get_structured_experience_levels(job)

    if len(levels) == 1:
        return next(iter(levels))

    return None


def extract_required_experience_years(job):
    searchable_text = normalize_text(
        " ".join([
            job.get("position_title") or "",
            job.get("job_description") or "",
        ])
    )

    if not searchable_text:
        return None

    detected_years = []

    for pattern in EXPERIENCE_YEAR_PATTERNS:
        for match in pattern.finditer(
            searchable_text
        ):
            try:
                years = int(
                    match.group(1)
                )
            except (
                TypeError,
                ValueError,
                IndexError,
            ):
                continue

            if 0 <= years <= 20:
                detected_years.append(years)

    if not detected_years:
        return None

    return max(detected_years)


def classify_experience_years(years):
    if years is None:
        return None

    if years <= 0:
        return "entry"

    if years <= 2:
        return "junior"

    if years <= 4:
        return "mid"

    return "senior"


def classify_job_experience(job):
    structured_levels = (
        get_structured_experience_levels(
            job
        )
    )

    if structured_levels:
        return structured_levels

    title = normalize_text(
        job.get("position_title")
    )

    detected_levels = set()

    for level, terms in EXPERIENCE_TERMS.items():
        if any(
            contains_phrase(title, term)
            for term in terms
        ):
            detected_levels.add(level)

    required_years = (
        extract_required_experience_years(
            job
        )
    )

    years_level = classify_experience_years(
        required_years
    )

    if years_level:
        detected_levels.add(
            years_level
        )

    detected_levels.update(
        get_implied_experience_levels(job)
    )

    if not detected_levels:
        detected_levels.add(
            "unspecified"
        )

    return detected_levels


def matches_role_title(job, profile):
    full_title = normalize_text(
        job.get("position_title")
    )
    title = get_core_role_title(full_title)

    if not title:
        return False

    if any(
        contains_phrase(
            full_title,
            normalize_role_phrase(
                excluded_term
            ),
        )
        for excluded_term
        in EXCLUDED_TITLE_TERMS
    ):
        return False

    keywords = [
        normalize_role_phrase(keyword)
        for keyword in parse_profile_values(
            profile.keywords
        )
        if (
            normalize_role_phrase(
                keyword
            ) not in GENERIC_KEYWORDS
            and normalize_role_phrase(
                keyword
            ) not in BROAD_ROLE_KEYWORDS
        )
    ]

    role_families = (
        get_profile_role_families(
            profile
        )
    )

    profile_keywords = {
        normalize_role_phrase(keyword)
        for keyword in parse_profile_values(
            profile.keywords
        )
    }

    if (
        "administrator"
        in profile_keywords
        and any(
            contains_phrase(
                title,
                pattern,
            )
            for pattern in (
                ALLOWED_ADMINISTRATOR_PATTERNS
            )
        )
    ):
        return True

    if (
        "systems" in profile_keywords
        and any(
            contains_phrase(
                title,
                pattern,
            )
            for pattern in {
                "systems engineer",
                "systems administrator",
                "systems support",
            }
        )
    ):
        return True

    if any(
        title_matches_role_family(
            title,
            family,
        )
        for family in role_families
    ):
        return True

    if not keywords:
        return any(
            contains_phrase(
                title,
                normalize_role_phrase(
                    technical_term
                ),
            )
            for technical_term
            in TECHNICAL_TITLE_TERMS
        )

    return any(
        contains_phrase(
            title,
            keyword,
        )
        for keyword in keywords
    )

def matches_experience_level(job, profile):
    requested_levels = (
        get_requested_experience_levels(
            profile
        )
    )

    if not requested_levels:
        return True

    # Trust a source's dedicated seniority field before
    # scanning the full description for years of experience.
    structured_levels = (
        get_structured_experience_levels(
            job
        )
    )

    if structured_levels:
        return bool(
            requested_levels.intersection(
                structured_levels
            )
        )

    required_years = (
        extract_required_experience_years(
            job
        )
    )

    years_level = classify_experience_years(
        required_years
    )

    if years_level:
        return years_level in requested_levels

    implied_levels = get_implied_experience_levels(job)

    if implied_levels:
        return bool(
            requested_levels.intersection(
                implied_levels
            )
        )

    detected_levels = classify_job_experience(
        job
    )

    if "unspecified" in detected_levels:
        # The company did not say what level this job is.
        # We only let it through when the user checked unspecified.
        return "unspecified" in requested_levels

    return bool(
        requested_levels.intersection(
            detected_levels
        )
    )


def parse_confidence(
    value,
    default=0.0,
):
    try:
        confidence = float(value)
    except (
        TypeError,
        ValueError,
    ):
        return default

    return max(
        0.0,
        min(confidence, 1.0),
    )



def normalize_workplace_type(value):
    value = normalize_text(value)

    mappings = {
        "remote": "remote",
        "fully remote": "remote",
        "full remote": "remote",
        "work from home": "remote",
        "distributed": "remote",
        "hybrid": "hybrid",
        "partially remote": "hybrid",
        "partial remote": "hybrid",
        "flexible hybrid": "hybrid",
        "on site": "on-site",
        "onsite": "on-site",
        "in office": "on-site",
        "office based": "on-site",
    }

    return mappings.get(value, value)


def get_job_workplace_type(job):
    explicit_type = normalize_workplace_type(
        job.get("workplace_type")
    )

    if explicit_type in {
        "remote",
        "hybrid",
        "on-site",
    }:
        return explicit_type

    if job.get("is_remote") is True:
        return "remote"

    location = normalize_text(
        job.get("location")
    )

    if any(
        contains_phrase(location, term)
        for term in REMOTE_TERMS
    ):
        return "remote"

    return "on-site"


def get_requested_workplace_types(profile):
    stored_value = getattr(
        profile,
        "workplace_types",
        None,
    )

    requested_types = {
        normalize_workplace_type(value)
        for value in parse_profile_values(
            stored_value
        )
    }

    requested_types = {
        value
        for value in requested_types
        if value in {
            "remote",
            "hybrid",
            "on-site",
        }
    }

    if requested_types:
        return requested_types

    # Existing profiles were remote-focused before
    # workplace_types became a separate setting.
    if getattr(profile, "remote_only", False):
        return {"remote"}

    remote_scope = normalize_text(
        getattr(
            profile,
            "remote_scope",
            "any",
        )
    )

    if remote_scope in {
        "worldwide",
        "selected_locations",
    }:
        return {"remote"}

    return {
        "remote",
        "hybrid",
        "on-site",
    }


def matches_workplace_type(job, profile):
    requested_types = (
        get_requested_workplace_types(
            profile
        )
    )

    job_workplace_type = (
        get_job_workplace_type(job)
    )

    return (
        job_workplace_type
        in requested_types
    )

def job_is_remote(job):
    return (
        get_job_workplace_type(job)
        == "remote"
    )


def has_specific_location(location):
    location = normalize_text(
        location
    )

    if not location:
        return False

    generic_remote_values = {
        "remote",
        "anywhere",
        "worldwide",
        "global",
        "remote worldwide",
        "anywhere in the world",
        "work from home",
    }

    location_parts = [
        part.strip()
        for part in re.split(
            r"[|;/]",
            location,
        )
        if part.strip()
    ]

    return any(
        part not in generic_remote_values
        for part in location_parts
    )


def has_uncertain_remote_location(
    job,
):
    location = normalize_text(
        job.get("location")
    )

    location_source = normalize_text(
        job.get("location_source")
    )

    location_confidence = (
        parse_confidence(
            job.get(
                "location_confidence"
            ),
            default=1.0,
        )
    )

    generic_remote_values = {
        "remote",
        "remote position",
        "remote role",
        "work from home",
    }

    fallback_sources = {
        "fallback_default",
        "unknown",
        "unspecified",
    }

    return (
        location in generic_remote_values
        and (
            location_confidence < 0.5
            or location_source
            in fallback_sources
        )
    )


def profile_requests_united_states(
    requested_locations,
):
    united_states_terms = {
        "united states",
        "united states of america",
        "usa",
        "u.s.a.",
        "us",
        "u.s.",
    }

    return any(
        normalize_text(location)
        in united_states_terms
        for location in requested_locations
    )


def matches_explicit_location(
    job_location,
    requested_locations,
):
    if not job_location:
        return False

    if (
        profile_requests_united_states(
            requested_locations
        )
        and location_is_united_states(
            job_location
        )
    ):
        return True

    expanded_locations = (
        expand_location_aliases(
            requested_locations
        )
    )

    return any(
        contains_phrase(
            job_location,
            requested_location,
        )
        for requested_location
        in expanded_locations
    )


def get_remote_candidate_scope(job):
    scope = normalize_text(
        job.get("remote_candidate_scope")
    )

    if scope in {
        "worldwide",
        "selected_locations",
    }:
        return scope

    return None


def get_remote_allowed_locations(job):
    raw_locations = job.get(
        "remote_allowed_locations"
    )

    if isinstance(raw_locations, str):
        return parse_profile_values(
            raw_locations
        )

    if isinstance(
        raw_locations,
        (list, tuple, set),
    ):
        return [
            normalize_text(location)
            for location in raw_locations
            if normalize_text(location)
        ]

    return []


def remote_job_is_worldwide(
    job,
    job_location,
):
    candidate_scope = (
        get_remote_candidate_scope(job)
    )

    if candidate_scope == "worldwide":
        return True

    if candidate_scope == "selected_locations":
        return False

    has_worldwide_term = any(
        contains_phrase(
            job_location,
            worldwide_term,
        )
        for worldwide_term
        in WORLDWIDE_REMOTE_TERMS
    )

    return (
        has_worldwide_term
        and not has_specific_location(
            job_location
        )
    )


def remote_job_matches_locations(
    job,
    job_location,
    requested_locations,
):
    candidate_scope = (
        get_remote_candidate_scope(job)
    )

    if candidate_scope == "worldwide":
        return True

    allowed_locations = (
        get_remote_allowed_locations(job)
    )

    if (
        candidate_scope == "selected_locations"
        and allowed_locations
    ):
        return any(
            matches_explicit_location(
                allowed_location,
                requested_locations,
            )
            for allowed_location
            in allowed_locations
        )

    if has_uncertain_remote_location(job):
        return False

    if not job_location:
        return False

    if remote_job_is_worldwide(
        job,
        job_location,
    ):
        return True

    return matches_explicit_location(
        job_location,
        requested_locations,
    )


def matches_location(job, profile):
    requested_locations = (
        parse_profile_values(
            profile.locations
        )
    )

    requested_locations = [
        location
        for location
        in requested_locations
        if location not in {
            "any",
            "all",
            "anywhere",
        }
    ]

    remote_scope = normalize_text(
        getattr(
            profile,
            "remote_scope",
            "any",
        )
    )

    workplace_type = (
        get_job_workplace_type(job)
    )

    job_location = normalize_text(
        job.get("location")
    )

    # Hybrid and on-site jobs always need to match
    # one of the user's selected physical locations.
    if workplace_type in {
        "hybrid",
        "on-site",
    }:
        if not requested_locations:
            return True

        return matches_explicit_location(
            job_location,
            requested_locations,
        )

    # A worldwide-remote profile must not accept
    # country-restricted remote jobs.
    if remote_scope == "worldwide":
        return remote_job_is_worldwide(
            job,
            job_location,
        )

    if remote_scope == "selected_locations":
        if not requested_locations:
            return False

        return remote_job_matches_locations(
            job,
            job_location,
            requested_locations,
        )

    # With no strict remote scope, selected locations
    # still apply when the user entered them.
    if not requested_locations:
        return True

    return remote_job_matches_locations(
        job,
        job_location,
        requested_locations,
    )


def normalize_employment_type(value):
    value = normalize_text(value)

    mappings = {
        "full time": "full-time",
        "fulltime": "full-time",
        "permanent": "full-time",
        "part time": "part-time",
        "parttime": "part-time",
        "intern": "internship",
        "internship": "internship",
        "contractor": "contract",
        "contract": "contract",
        "temporary": "temporary",
        "temp": "temporary",
        "freelance": "freelance",
    }

    return mappings.get(value, value)


def matches_employment_type(job, profile):
    requested_types = {
        normalize_employment_type(value)
        for value in parse_profile_values(
            profile.employment_types
        )
        if value not in {"all", "any"}
    }

    if not requested_types:
        return True

    job_type = normalize_employment_type(
        job.get("employment_type")
    )

    if not job_type:
        return False

    return job_type in requested_types


def detect_visa_sponsorship(job):
    explicit_value = normalize_text(
        job.get("visa_sponsorship")
    )

    positive_values = {
        "yes",
        "true",
        "available",
        "provided",
        "offered",
        "sponsored",
        "sponsorship available",
        "visa support available",
    }

    negative_values = {
        "no",
        "false",
        "unavailable",
        "not available",
        "not offered",
        "no sponsorship",
    }

    unknown_values = {
        "",
        "unknown",
        "not specified",
        "unspecified",
        "n/a",
        "none listed",
    }

    if explicit_value in positive_values:
        return "yes"

    if explicit_value in negative_values:
        return "no"

    if explicit_value in unknown_values:
        explicit_value = ""

    searchable_text = normalize_text(
        " ".join([
            job.get("position_title") or "",
            job.get("job_description") or "",
        ])
    )

    if any(
        phrase in searchable_text
        for phrase in VISA_NEGATIVE_TERMS
    ):
        return "no"

    if any(
        phrase in searchable_text
        for phrase in VISA_POSITIVE_TERMS
    ):
        return "yes"

    return "unknown"


def normalize_overseas_applicant_status(value):
    normalized = normalize_text(value)

    if normalized in {
        "yes",
        "open",
        "allowed",
        "open to overseas applicants",
        "overseas applicants welcome",
    }:
        return "yes"

    if normalized in {
        "no",
        "not allowed",
        "residents only",
        "japan residents only",
        "current residents only",
    }:
        return "no"

    if normalized in {
        "not applicable",
        "n/a",
        "na",
    }:
        return "not_applicable"

    return "unknown"


def matches_overseas_applicant_preference(
    job,
    profile,
):
    preference = normalize_text(
        getattr(
            profile,
            "overseas_applicant_preference",
            "any",
        )
    )

    if preference in {
        "",
        "any",
        "all",
    }:
        return True

    status = normalize_overseas_applicant_status(
        job.get("overseas_applicant_status")
    )

    if status == "not_applicable":
        return True

    return status == preference


def matches_visa_requirement(job, profile):
    requested_visa_status = normalize_text(
        getattr(
            profile,
            "visa_preference",
            "any"
        )
    )

    if requested_visa_status in {
        "",
        "any",
        "all",
    }:
        return True

    detected_status = detect_visa_sponsorship(job)

    return detected_status == requested_visa_status


def parse_job_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value

    elif isinstance(value, (int, float)):
        timestamp = float(value)

        # Some APIs expose Unix milliseconds instead of seconds.
        if timestamp > 100_000_000_000:
            timestamp /= 1000

        try:
            parsed = datetime.fromtimestamp(
                timestamp,
                tz=timezone.utc,
            )
        except (
            OverflowError,
            OSError,
            ValueError,
        ):
            return None

    else:
        text = str(value).strip()

        if not text:
            return None

        # Algolia can return Unix timestamps as numeric strings.
        if text.isdigit():
            timestamp = float(text)

            if timestamp > 100_000_000_000:
                timestamp /= 1000

            try:
                parsed = datetime.fromtimestamp(
                    timestamp,
                    tz=timezone.utc,
                )
            except (
                OverflowError,
                OSError,
                ValueError,
            ):
                return None
        else:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"

            parsed = None

            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                for date_format in (
                    "%Y-%m-%d",
                    "%B %d, %Y",
                    "%b %d, %Y",
                ):
                    try:
                        parsed = datetime.strptime(
                            text,
                            date_format,
                        )
                        break
                    except ValueError:
                        continue

            if parsed is None:
                return None

    if parsed.tzinfo is None:
        return parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def matches_posting_age(job, profile):
    try:
        maximum_age_days = int(
            getattr(
                profile,
                "maximum_posting_age_days",
                395,
            )
            or 395
        )
    except (TypeError, ValueError):
        maximum_age_days = 395

    published_at = parse_job_datetime(
        job.get("published_at")
        or job.get("date_posted")
    )

    # Keep jobs from sources that do not expose a reliable date.
    if published_at is None:
        return True

    cutoff = (
        datetime.now(timezone.utc)
        - timedelta(days=maximum_age_days)
    )

    return published_at >= cutoff


def job_matches_profile(
    job,
    profile,
):
    required_experience_years = (
        extract_required_experience_years(
            job
        )
    )

    detected_experience_levels = (
        classify_job_experience(
            job
        )
    )

    checks = {
        "role": matches_role_title(
            job,
            profile,
        ),
        "experience": (
            matches_experience_level(
                job,
                profile,
            )
        ),
        "location": matches_location(
            job,
            profile,
        ),
        "workplace_type": (
            matches_workplace_type(
                job,
                profile,
            )
        ),
        "employment_type": (
            matches_employment_type(
                job,
                profile,
            )
        ),
        "visa": (
            matches_visa_requirement(
                job,
                profile,
            )
        ),
        "overseas": (
            matches_overseas_applicant_preference(
                job,
                profile,
            )
        ),
        "posting_age": (
            matches_posting_age(
                job,
                profile,
            )
        ),
    }

    matched = all(
        checks.values()
    )

    failed_checks = [
        name
        for name, passed
        in checks.items()
        if not passed
    ]

    record_match_diagnostics(
        matched,
        failed_checks,
    )

    if not matched and JOB_MATCH_DEBUG:
        print(
            f"JOB FILTER REJECTED | "
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
            f"Experience years: "
            f"{required_experience_years} | "
            f"Experience levels: "
            f"{sorted(detected_experience_levels)} | "
            f"Failed: {failed_checks}"
        )

    return matched
