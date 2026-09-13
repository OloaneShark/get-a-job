from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import g, has_app_context, has_request_context

from models import ApplicationHostClassification, db


SUPPORTED_WRAPPER = "supported_wrapper"
NO_SUPPORTED_ATS = "no_supported_ats"
UNSUPPORTED_DESTINATION = "unsupported_destination"

BLOCKING_CLASSIFICATIONS = frozenset(
    {
        NO_SUPPORTED_ATS,
        UNSUPPORTED_DESTINATION,
    }
)
VALID_CLASSIFICATIONS = (
    BLOCKING_CLASSIFICATIONS
    | {SUPPORTED_WRAPPER}
)
SUPPORTED_WRAPPER_ADAPTERS = frozenset(
    {
        "greenhouse_hosted",
        "lever_hosted",
        "ashby_hosted",
    }
)

POSITIVE_TTL = timedelta(days=30)
NEGATIVE_TTL = timedelta(hours=24)
REQUEST_CACHE_KEY = "_jobfinitum_application_host_classifications"


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_application_hostname(value):
    try:
        hostname = (
            urlsplit(str(value or "").strip()).hostname
            or ""
        ).lower().rstrip(".")
    except ValueError:
        return ""

    if hostname.startswith("www."):
        hostname = hostname[4:]

    return hostname


def _request_cache():
    if not has_request_context():
        return None

    cache = getattr(g, REQUEST_CACHE_KEY, None)
    if cache is None:
        cache = {}
        setattr(g, REQUEST_CACHE_KEY, cache)
    return cache


def prime_host_classification_cache(values):
    if not has_app_context():
        return {}

    hostnames = {
        normalize_application_hostname(value)
        for value in values
    }
    hostnames.discard("")

    if not hostnames:
        return {}

    request_cache = _request_cache()
    missing = (
        hostnames
        if request_cache is None
        else hostnames.difference(request_cache)
    )
    records_by_host = {}

    if missing:
        records = (
            ApplicationHostClassification.query
            .filter(
                ApplicationHostClassification.hostname.in_(missing)
            )
            .all()
        )
        records_by_host = {
            record.hostname: record
            for record in records
        }

        if request_cache is not None:
            for hostname in missing:
                request_cache[hostname] = records_by_host.get(hostname)

    if request_cache is not None:
        return {
            hostname: request_cache.get(hostname)
            for hostname in hostnames
        }

    return {
        hostname: records_by_host.get(hostname)
        for hostname in hostnames
    }


def lookup_host_classification(value):
    if not has_app_context():
        return None

    hostname = normalize_application_hostname(value)
    if not hostname:
        return None

    request_cache = _request_cache()
    if request_cache is not None and hostname in request_cache:
        return request_cache[hostname]

    record = (
        ApplicationHostClassification.query
        .filter_by(hostname=hostname)
        .first()
    )

    if request_cache is not None:
        request_cache[hostname] = record

    return record


def host_classification_is_active(record, *, now=None):
    if record is None:
        return False

    current = now or utcnow_naive()
    return (
        record.expires_at is not None
        and record.expires_at > current
    )


def host_scan_decision(value, *, now=None):
    record = lookup_host_classification(value)
    if not host_classification_is_active(record, now=now):
        return None

    if record.classification == SUPPORTED_WRAPPER:
        return True

    if record.classification in BLOCKING_CLASSIFICATIONS:
        return False

    return None


def active_blocking_host_classification(value, *, now=None):
    record = lookup_host_classification(value)
    if (
        host_classification_is_active(record, now=now)
        and record.classification in BLOCKING_CLASSIFICATIONS
    ):
        return record
    return None


def remember_host_classification(
    value,
    classification,
    *,
    adapter_name=None,
    evidence_kind=None,
    evidence_url=None,
    reason=None,
    now=None,
):
    if not has_app_context():
        return None

    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError("Unsupported application-host classification.")

    if (
        classification == SUPPORTED_WRAPPER
        and adapter_name not in SUPPORTED_WRAPPER_ADAPTERS
    ):
        raise ValueError(
            "A supported wrapper classification requires a hosted ATS adapter."
        )

    hostname = normalize_application_hostname(value)
    if not hostname:
        return None

    current = now or utcnow_naive()
    record = (
        ApplicationHostClassification.query
        .filter_by(hostname=hostname)
        .first()
    )

    if (
        record is not None
        and record.classification == SUPPORTED_WRAPPER
        and classification in BLOCKING_CLASSIFICATIONS
        and host_classification_is_active(record, now=current)
    ):
        return record

    if record is None:
        record = ApplicationHostClassification(hostname=hostname)
        db.session.add(record)

    ttl = (
        POSITIVE_TTL
        if classification == SUPPORTED_WRAPPER
        else NEGATIVE_TTL
    )
    record.classification = classification
    record.adapter_name = (
        str(adapter_name or "").strip()[:80]
        or None
    )
    record.evidence_kind = (
        str(evidence_kind or "").strip()[:80]
        or None
    )
    record.evidence_url = (
        str(evidence_url or value or "").strip()[:1000]
        or None
    )
    record.reason = str(reason or "").strip() or None
    record.observed_at = current
    record.expires_at = current + ttl

    request_cache = _request_cache()
    if request_cache is not None:
        request_cache[hostname] = record

    return record
