import hashlib
import re
import unicodedata


CROSS_SOURCE_DEDUPE_FAMILIES = (
    frozenset({
        "tokyodev",
        "japandev",
    }),
)


def normalize_identity_text(value):
    text = unicodedata.normalize(
        "NFKC",
        str(value or ""),
    ).casefold()

    text = text.replace(
        "&",
        " and ",
    )

    return re.sub(
        r"[^a-z0-9]+",
        " ",
        text,
    ).strip()


def normalize_source_identity(value):
    return re.sub(
        r"[^a-z0-9]+",
        "",
        str(value or "").casefold(),
    )


def source_dedupe_family(value):
    source = normalize_source_identity(
        value
    )

    for family in CROSS_SOURCE_DEDUPE_FAMILIES:
        if source in family:
            return family

    return None


def compatible_cross_source_pair(
    first_source,
    second_source,
):
    first = normalize_source_identity(
        first_source
    )
    second = normalize_source_identity(
        second_source
    )

    if not first or not second or first == second:
        return False

    first_family = source_dedupe_family(
        first
    )

    return (
        first_family is not None
        and second in first_family
    )


def title_identity_is_specific_enough(
    value,
):
    normalized = normalize_identity_text(
        value
    )

    if not normalized:
        return False

    meaningful_tokens = [
        token
        for token in normalized.split()
        if len(token) > 1
    ]

    return len(meaningful_tokens) >= 3


def normalize_employment_identity(value):
    return normalize_identity_text(
        value
    )


def location_is_japan_compatible(value):
    normalized = normalize_identity_text(
        value
    )

    if not normalized:
        return True

    tokens = set(
        normalized.split()
    )

    return bool(
        tokens.intersection({
            "japan",
            "jp",
            "tokyo",
            "osaka",
            "kyoto",
            "nagoya",
            "fukuoka",
            "yokohama",
            "shibuya",
            "minato",
        })
    )


UNKNOWN_COMPANY_IDENTITIES = {
    "",
    "unknown",
    "unknown company",
}

UNKNOWN_TITLE_IDENTITIES = {
    "",
    "untitled",
    "untitled position",
}

GENERIC_LOCATION_TOKENS = {
    "remote",
    "hybrid",
    "onsite",
    "on",
    "site",
    "worldwide",
    "global",
    "anywhere",
    "work",
    "from",
    "home",
    "fully",
    "position",
    "role",
}


def normalize_location_identity(value):
    normalized = normalize_identity_text(
        value
    )

    replacements = (
        (
            r"\bunited states of america\b",
            "united states",
        ),
        (
            r"\bu s a\b",
            "united states",
        ),
        (
            r"\busa\b",
            "united states",
        ),
        (
            r"\bu s\b",
            "united states",
        ),
        (
            r"\bus\b",
            "united states",
        ),
        (
            r"\bgreat britain\b",
            "united kingdom",
        ),
        (
            r"\bu k\b",
            "united kingdom",
        ),
        (
            r"\buk\b",
            "united kingdom",
        ),
    )

    for pattern, replacement in replacements:
        normalized = re.sub(
            pattern,
            replacement,
            normalized,
        )

    return re.sub(
        r"\s+",
        " ",
        normalized,
    ).strip()


def location_identity_tokens(value):
    normalized = normalize_location_identity(
        value
    )

    return {
        token
        for token in normalized.split()
        if (
            token
            and token
            not in GENERIC_LOCATION_TOKENS
        )
    }


def locations_are_compatible(
    first_location,
    second_location,
):
    first_normalized = (
        normalize_location_identity(
            first_location
        )
    )
    second_normalized = (
        normalize_location_identity(
            second_location
        )
    )

    if (
        not first_normalized
        and not second_normalized
    ):
        return True

    if (
        not first_normalized
        or not second_normalized
    ):
        return False

    if (
        first_normalized
        == second_normalized
    ):
        return True

    first_tokens = location_identity_tokens(
        first_location
    )
    second_tokens = location_identity_tokens(
        second_location
    )

    if (
        not first_tokens
        and not second_tokens
    ):
        return True

    if (
        not first_tokens
        or not second_tokens
    ):
        return False

    return (
        first_tokens.issubset(
            second_tokens
        )
        or second_tokens.issubset(
            first_tokens
        )
    )


def description_identity_tokens(value):
    normalized = normalize_identity_text(
        value
    )

    return [
        token
        for token in normalized.split()
        if len(token) > 1
    ]


def description_shingles(
    value,
    width=3,
):
    tokens = description_identity_tokens(
        value
    )

    if len(tokens) < 35:
        return set()

    return {
        tuple(
            tokens[
                index:index + width
            ]
        )
        for index in range(
            0,
            len(tokens) - width + 1,
        )
    }


def description_similarity_metrics(
    first_description,
    second_description,
):
    first = description_shingles(
        first_description
    )
    second = description_shingles(
        second_description
    )

    if not first or not second:
        return {
            "shared": 0,
            "jaccard": 0.0,
            "containment": 0.0,
        }

    intersection = (
        first.intersection(
            second
        )
    )
    union = first.union(
        second
    )

    shared = len(
        intersection
    )
    jaccard = (
        shared / len(union)
        if union
        else 0.0
    )
    containment = (
        shared
        / min(
            len(first),
            len(second),
        )
    )

    return {
        "shared": shared,
        "jaccard": jaccard,
        "containment": containment,
    }


def descriptions_are_highly_similar(
    first_description,
    second_description,
):
    metrics = (
        description_similarity_metrics(
            first_description,
            second_description,
        )
    )

    if metrics["shared"] < 30:
        return False

    return (
        metrics["jaccard"] >= 0.78
        or metrics["containment"] >= 0.92
    )


def family_cross_source_jobs_match(
    existing_job,
    incoming_job,
):
    existing_company = (
        normalize_identity_text(
            getattr(
                existing_job,
                "company_name",
                None,
            )
        )
    )
    incoming_company = (
        normalize_identity_text(
            incoming_job.get(
                "company_name"
            )
        )
    )

    if (
        not existing_company
        or existing_company
        != incoming_company
    ):
        return False

    existing_title = (
        normalize_identity_text(
            getattr(
                existing_job,
                "position_title",
                None,
            )
        )
    )
    incoming_title = (
        normalize_identity_text(
            incoming_job.get(
                "position_title"
            )
        )
    )

    if (
        not existing_title
        or existing_title
        != incoming_title
    ):
        return False

    if not title_identity_is_specific_enough(
        incoming_title
    ):
        return False

    existing_employment = (
        normalize_employment_identity(
            getattr(
                existing_job,
                "employment_type",
                None,
            )
        )
    )
    incoming_employment = (
        normalize_employment_identity(
            incoming_job.get(
                "employment_type"
            )
        )
    )

    if (
        existing_employment
        and incoming_employment
        and existing_employment
        != incoming_employment
    ):
        return False

    if not (
        location_is_japan_compatible(
            getattr(
                existing_job,
                "location",
                None,
            )
        )
        and location_is_japan_compatible(
            incoming_job.get(
                "location"
            )
        )
    ):
        return False

    return True


def generic_cross_source_jobs_match(
    existing_job,
    incoming_job,
):
    existing_company = (
        normalize_identity_text(
            getattr(
                existing_job,
                "company_name",
                None,
            )
        )
    )
    incoming_company = (
        normalize_identity_text(
            incoming_job.get(
                "company_name"
            )
        )
    )

    if (
        existing_company
        in UNKNOWN_COMPANY_IDENTITIES
        or incoming_company
        in UNKNOWN_COMPANY_IDENTITIES
        or existing_company
        != incoming_company
    ):
        return False

    existing_title = (
        normalize_identity_text(
            getattr(
                existing_job,
                "position_title",
                None,
            )
        )
    )
    incoming_title = (
        normalize_identity_text(
            incoming_job.get(
                "position_title"
            )
        )
    )

    if (
        existing_title
        in UNKNOWN_TITLE_IDENTITIES
        or incoming_title
        in UNKNOWN_TITLE_IDENTITIES
        or existing_title
        != incoming_title
    ):
        return False

    if not title_identity_is_specific_enough(
        incoming_title
    ):
        return False

    existing_employment = (
        normalize_employment_identity(
            getattr(
                existing_job,
                "employment_type",
                None,
            )
        )
    )
    incoming_employment = (
        normalize_employment_identity(
            incoming_job.get(
                "employment_type"
            )
        )
    )

    if (
        existing_employment
        and incoming_employment
        and existing_employment
        != incoming_employment
    ):
        return False

    if not locations_are_compatible(
        getattr(
            existing_job,
            "location",
            None,
        ),
        incoming_job.get(
            "location"
        ),
    ):
        return False

    return descriptions_are_highly_similar(
        getattr(
            existing_job,
            "job_description",
            None,
        ),
        incoming_job.get(
            "job_description"
        ),
    )


def cross_source_jobs_match(
    existing_job,
    incoming_job,
):
    existing_source = getattr(
        existing_job,
        "source",
        None,
    )
    incoming_source = (
        incoming_job.get(
            "source"
        )
    )

    existing_normalized = (
        normalize_source_identity(
            existing_source
        )
    )
    incoming_normalized = (
        normalize_source_identity(
            incoming_source
        )
    )

    if (
        not existing_normalized
        or not incoming_normalized
        or existing_normalized
        == incoming_normalized
    ):
        return False

    if compatible_cross_source_pair(
        existing_source,
        incoming_source,
    ):
        return family_cross_source_jobs_match(
            existing_job,
            incoming_job,
        )

    return generic_cross_source_jobs_match(
        existing_job,
        incoming_job,
    )


def build_job_fingerprint(
    company,
    position,
    location,
    posting_url
):
    normalized = "|".join([
        (company or "").strip().lower(),
        (position or "").strip().lower(),
        (location or "").strip().lower(),
        (posting_url or "").strip().lower().rstrip("/")
    ])

    return hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()
