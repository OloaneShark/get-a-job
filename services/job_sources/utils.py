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


def cross_source_jobs_match(
    existing_job,
    incoming_job,
):
    if not compatible_cross_source_pair(
        getattr(
            existing_job,
            "source",
            None,
        ),
        incoming_job.get(
            "source"
        ),
    ):
        return False

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
