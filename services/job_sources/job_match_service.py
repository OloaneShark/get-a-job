
import re


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
    return re.sub(
        r"\s+",
        " ",
        str(value or "").strip().lower()
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

    if not detected_levels:
        detected_levels.add(
            "unspecified"
        )

    return detected_levels


def matches_role_title(job, profile):
    title = normalize_text(
        job.get("position_title")
    )

    if not title:
        return False

    if any(
        excluded_term in title
        for excluded_term in EXCLUDED_TITLE_TERMS
    ):
        return False

    keywords = [
        keyword
        for keyword in parse_profile_values(
            profile.keywords
        )
        if keyword not in GENERIC_KEYWORDS
    ]

    if not keywords:
        return any(
            technical_term in title
            for technical_term in TECHNICAL_TITLE_TERMS
        )

    return any(
        contains_phrase(title, keyword)
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

    detected_levels = classify_job_experience(
        job
    )

    if "unspecified" in detected_levels:
        # An unlabelled role may still be acceptable for
        # entry, junior, or mid searches, but not internship.
        return bool(
            requested_levels.intersection({
                "entry",
                "junior",
                "mid",
            })
        )

    return bool(
        requested_levels.intersection(
            detected_levels
        )
    )


def job_is_remote(job):
    if job.get("is_remote") is True:
        return True

    workplace_type = normalize_text(
        job.get("workplace_type")
    )

    location = normalize_text(
        job.get("location")
    )

    return (
        workplace_type == "remote"
        or any(term in location for term in REMOTE_TERMS)
    )


def matches_location(job, profile):
    requested_locations = parse_profile_values(
        profile.locations
    )

    requested_locations = [
        location
        for location in requested_locations
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
            "any"
        )
    )

    is_remote = job_is_remote(job)

    job_location = normalize_text(
        job.get("location")
    )

    if remote_scope == "worldwide":
        return is_remote

    if remote_scope == "selected_locations":
        if not is_remote:
            return False

        if not requested_locations:
            return False

        # Explicit worldwide remote jobs are available
        # from the selected location.
        if not job_location:
            return True

        has_worldwide_term = any(
            contains_phrase(
                job_location,
                worldwide_term
            )
            for worldwide_term
            in WORLDWIDE_REMOTE_TERMS
        )

        if (
            has_worldwide_term
            and not has_specific_location(
                job_location
            )
        ):
            return True

        requesting_united_states = any(
            requested_location in {
                "united states",
                "united states of america",
                "usa",
                "u.s.a.",
                "us",
                "u.s.",
            }
            for requested_location
            in requested_locations
        )

        if (
            requesting_united_states
            and location_is_united_states(
                job_location
            )
        ):
            return True

        expanded_locations = expand_location_aliases(
            requested_locations
        )

        return any(
            contains_phrase(
                job_location,
                requested_location
            )
            for requested_location
            in expanded_locations
        )

    if not requested_locations:
        return True

    if not job_location:
        return False

    requesting_united_states = any(
        requested_location in {
            "united states",
            "united states of america",
            "usa",
            "u.s.a.",
            "us",
            "u.s.",
        }
        for requested_location
        in requested_locations
    )

    if (
        requesting_united_states
        and location_is_united_states(
            job_location
        )
    ):
        return True

    expanded_locations = expand_location_aliases(
        requested_locations
    )

    return any(
        contains_phrase(
            job_location,
            requested_location
        )
        for requested_location
        in expanded_locations
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


def job_matches_profile(job, profile):
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
            profile
        ),
        "experience": matches_experience_level(
            job,
            profile
        ),
        "location": matches_location(
            job,
            profile
        ),
        "employment_type": matches_employment_type(
            job,
            profile
        ),
        "visa": matches_visa_requirement(
            job,
            profile
        ),
    }

    matched = all(checks.values())

    if not matched:
        failed_checks = [
            name
            for name, passed in checks.items()
            if not passed
        ]

        print(
            f"JOB FILTER REJECTED | "
            f"Title: {job.get('position_title')} | "
            f"Company: {job.get('company_name')} | "
            f"Experience years: "
            f"{required_experience_years} | "
            f"Experience levels: "
            f"{sorted(detected_experience_levels)} | "
            f"Failed: {failed_checks}"
        )

    return matched


def has_specific_location(location):
    location = normalize_text(location)

    if not location:
        return False

    generic_remote_values = {
        "remote",
        "anywhere",
        "worldwide",
        "global",
        "remote worldwide",
    }

    location_parts = [
        part.strip()
        for part in re.split(
            r"[|;/]",
            location
        )
        if part.strip()
    ]

    return any(
        part not in generic_remote_values
        for part in location_parts
    )
    
    
