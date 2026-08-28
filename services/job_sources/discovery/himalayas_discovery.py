import html
import re
from urllib.parse import parse_qs, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from services.job_sources.discovery.source_discovery import (
    detect_source_type,
)


URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+",
    flags=re.IGNORECASE,
)

TRAILING_URL_PUNCTUATION = ".,;:!?)]}"


def clean_candidate_url(value):
    cleaned = html.unescape(
        str(value or "")
    ).strip()

    cleaned = cleaned.replace(
        "\\/",
        "/",
    ).rstrip(
        TRAILING_URL_PUNCTUATION
    )

    try:
        parsed = urlsplit(cleaned)
    except ValueError:
        return None

    if (
        parsed.scheme.lower()
        not in {"http", "https"}
        or not parsed.hostname
    ):
        return None

    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc,
            parsed.path,
            parsed.query,
            "",
        )
    )


def is_job_specific_source_url(
    url,
    source_type,
):
    parsed = urlsplit(url)
    path_parts = [
        part
        for part in parsed.path.split("/")
        if part
    ]
    lowered_parts = [
        part.lower()
        for part in path_parts
    ]

    if source_type == "lever":
        return len(path_parts) >= 2

    if source_type == "greenhouse":
        query = parse_qs(parsed.query)

        return (
            bool(query.get("gh_jid"))
            or (
                "jobs" in lowered_parts
                and lowered_parts.index("jobs")
                + 1
                < len(path_parts)
            )
        )

    if source_type == "ashby":
        return len(path_parts) >= 2

    if source_type == "workday":
        return "job" in lowered_parts

    if source_type == "recruitee":
        return (
            "o" in lowered_parts
            and lowered_parts.index("o")
            + 1
            < len(path_parts)
        )

    if source_type == "bamboohr":
        return (
            "careers" in lowered_parts
            and lowered_parts.index("careers")
            + 1
            < len(path_parts)
        )

    if source_type == "workable":
        return (
            "j" in lowered_parts
            and lowered_parts.index("j")
            + 1
            < len(path_parts)
        )

    return False


def supported_source_record(
    value,
    *,
    context="",
):
    url = clean_candidate_url(value)

    if not url:
        return None

    try:
        (
            source_type,
            source_identifier,
        ) = detect_source_type(url)
    except ValueError:
        return None

    normalized_context = " ".join(
        str(context or "").lower().split()
    )
    application_context = any(
        phrase in normalized_context
        for phrase in (
            "apply",
            "application",
            "open position",
            "open role",
            "careers",
            "jobs",
        )
    )
    job_specific = (
        is_job_specific_source_url(
            url,
            source_type,
        )
    )

    return {
        "url": url,
        "source_type": source_type,
        "source_identifier": source_identifier,
        "job_specific": job_specific,
        "direct_application": bool(
            job_specific
            and application_context
        ),
    }


def extract_supported_source_records(raw_html):
    if not raw_html:
        return []

    markup = html.unescape(
        str(raw_html)
    ).replace(
        "\\/",
        "/",
    )
    soup = BeautifulSoup(
        markup,
        "html.parser",
    )
    records = []

    for anchor in soup.select("a[href]"):
        record = supported_source_record(
            anchor.get("href"),
            context=anchor.get_text(
                " ",
                strip=True,
            ),
        )

        if record:
            records.append(record)

    plain_text = soup.get_text(
        " ",
        strip=True,
    )

    for match in URL_PATTERN.finditer(
        plain_text
    ):
        context_start = max(
            0,
            match.start() - 100,
        )
        context_end = min(
            len(plain_text),
            match.end() + 100,
        )
        record = supported_source_record(
            match.group(0),
            context=plain_text[
                context_start:context_end
            ],
        )

        if record:
            records.append(record)

    deduplicated = {}

    for record in records:
        key = (
            record["source_type"],
            str(
                record["source_identifier"]
            ).casefold(),
        )
        existing = deduplicated.get(key)

        if existing is None:
            deduplicated[key] = record
            continue

        if (
            record["direct_application"]
            and not existing[
                "direct_application"
            ]
        ):
            deduplicated[key] = record
            continue

        if (
            record["job_specific"]
            and not existing[
                "job_specific"
            ]
        ):
            deduplicated[key] = record

    return list(
        deduplicated.values()
    )


def direct_application_url(records):
    for record in records or []:
        if record.get(
            "direct_application"
        ):
            return record.get("url")

    return None
