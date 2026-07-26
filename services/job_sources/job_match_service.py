
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


def contains_phrase(text, phrase):
    pattern = (
        r"(?<!\w)"
        + re.escape(phrase)
        + r"(?!\w)"
    )

    return bool(re.search(pattern, text))


def get_requested_experience_levels(profile):
    value = getattr(
        profile,
        "experience_levels",
        None
    )

    return set(parse_profile_values(value))


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

    if not detected_levels:
        detected_levels.add("unspecified")

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

    # First, honor direct user keyword matches in the title.
    if any(
        contains_phrase(title, keyword)
        for keyword in keywords
    ):
        return True

    # Then allow known technical-role titles.
    return any(
        technical_term in title
        for technical_term in TECHNICAL_TITLE_TERMS
    )


def matches_experience_level(job, profile):
    requested_levels = get_requested_experience_levels(
        profile
    )

    if not requested_levels:
        return True

    detected_levels = classify_job_experience(job)

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
    locations = parse_profile_values(
        profile.locations
    )

    locations = [
        location
        for location in locations
        if location not in {
            "any",
            "all",
            "anywhere"
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

    if remote_scope == "worldwide":
        return is_remote

    if remote_scope == "selected_locations":
        if not is_remote:
            return False

        if not locations:
            return False

        job_location = normalize_text(
            job.get("location")
        )

        if not job_location:
            return False

        return any(
            location in job_location
            for location in locations
        )

    if not locations:
        return True

    job_location = normalize_text(
        job.get("location")
    )

    if not job_location:
        return False

    return any(
        location in job_location
        for location in locations
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
            f"Failed: {failed_checks}"
        )

    return matched


