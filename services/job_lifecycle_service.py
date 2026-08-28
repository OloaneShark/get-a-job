import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from models import (
    ApplicationPackage,
    ApplicationSubmissionAttempt,
    AutoApplyCandidate,
    CachedSourceJob,
    DiscoveredJob,
    JobApplication,
    JobLifecycleScanState,
    JobPostingHealth,
    SuppressedJob,
    db,
)
from services.job_identity_service import (
    canonical_job_url,
    job_url_key,
)
from services.job_sources.shared_job_cache import (
    CACHE_RETENTION_DAYS,
)


HEALTH_CHECK_BATCH_SIZE = 20
HEALTH_RECHECK_INTERVAL = timedelta(hours=24)
REJECTED_HEALTH_RECHECK_INTERVAL = timedelta(minutes=5)
HEALTH_SCAN_STATE_NAME = "cached_source_jobs"
DISCOVERED_HEALTH_SCAN_STATE_NAME = "discovered_jobs"
REQUEST_TIMEOUT = (5, 15)

CLOSED_PAGE_PATTERNS = (
    re.compile(r"\bthis job is (?:now )?closed\b", re.IGNORECASE),
    re.compile(r"\bthis job has been closed\b", re.IGNORECASE),
    re.compile(r"\bjob is no longer available\b", re.IGNORECASE),
    re.compile(r"\b(?:job|position|role) is no longer (?:active|open|available)\b", re.IGNORECASE),
    re.compile(r"\bjob (?:posting )?has (?:been )?closed\b", re.IGNORECASE),
    re.compile(r"\bthis job (?:has expired|is expired)\b", re.IGNORECASE),
    re.compile(r"\bthis position (?:is|has been) (?:closed|filled)\b", re.IGNORECASE),
    re.compile(r"\bno longer (?:accepting|considering) (?:applications|applicants)\b", re.IGNORECASE),
    re.compile(r"\bapplications? (?:are|is) (?:now )?closed\b", re.IGNORECASE),
    re.compile(r"\bjob posting (?:is|has) expired\b", re.IGNORECASE),
    re.compile(r"\bcouldn['\u2019]t find this job\b", re.IGNORECASE),
)


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def suppressed_job_identity_sets(user_id):
    rows = (
        db.session.query(
            SuppressedJob.fingerprint,
            SuppressedJob.url_key,
        )
        .filter(
            SuppressedJob.user_id == user_id
        )
        .all()
    )

    return (
        {
            row[0]
            for row in rows
            if row[0]
        },
        {
            row[1]
            for row in rows
            if row[1]
        },
    )


def job_is_suppressed(
    user_id,
    *,
    fingerprint=None,
    posting_url=None,
):
    fingerprint = str(fingerprint or "").strip()
    url_key = job_url_key(posting_url)
    clauses = []

    if fingerprint:
        clauses.append(
            SuppressedJob.fingerprint
            == fingerprint
        )

    if url_key:
        clauses.append(
            SuppressedJob.url_key
            == url_key
        )

    if not clauses:
        return False

    return db.session.query(
        SuppressedJob.id
    ).filter(
        SuppressedJob.user_id == user_id,
        db.or_(*clauses),
    ).first() is not None


def globally_closed_job_url_keys(urls):
    url_keys = {
        job_url_key(url)
        for url in urls
        if job_url_key(url)
    }

    if not url_keys:
        return set()

    return {
        row[0]
        for row in (
            db.session.query(
                JobPostingHealth.url_key
            )
            .filter(
                JobPostingHealth.status
                == "Closed",
                JobPostingHealth.url_key.in_(
                    url_keys
                ),
            )
            .all()
        )
    }


def job_is_globally_closed(posting_url):
    url_key = job_url_key(posting_url)

    if not url_key:
        return False

    return db.session.query(
        JobPostingHealth.url_key
    ).filter(
        JobPostingHealth.url_key == url_key,
        JobPostingHealth.status == "Closed",
    ).first() is not None


def suppress_discovered_job(
    job,
    *,
    reason,
):
    canonical_url = canonical_job_url(
        job.posting_url
        or job.apply_url
    )
    url_key = job_url_key(canonical_url)
    fingerprint = str(
        job.fingerprint or ""
    ).strip()

    if not fingerprint or not url_key:
        return None

    matches = (
        SuppressedJob.query
        .filter(
            SuppressedJob.user_id
            == job.user_id,
            db.or_(
                SuppressedJob.fingerprint
                == fingerprint,
                SuppressedJob.url_key
                == url_key,
            ),
        )
        .order_by(SuppressedJob.id.asc())
        .all()
    )

    if matches:
        suppression = matches[0]

        for duplicate in matches[1:]:
            db.session.delete(duplicate)
    else:
        suppression = SuppressedJob(
            user_id=job.user_id,
            fingerprint=fingerprint,
            url_key=url_key,
        )
        db.session.add(suppression)

    suppression.fingerprint = fingerprint
    suppression.url_key = url_key
    suppression.posting_url = canonical_url[:1000]
    suppression.source = str(
        job.source or ""
    )[:80] or None
    suppression.company_name = str(
        job.company_name or ""
    )[:150] or None
    suppression.position_title = str(
        job.position_title or ""
    )[:150] or None
    suppression.reason = str(
        reason or "Removed"
    )[:80]

    return suppression


def _candidate_was_submitted(
    candidate,
    package,
    application,
):
    return (
        str(
            candidate.execution_status or ""
        ).strip().lower()
        == "submitted"
        or (
            package is not None
            and str(
                package.status or ""
            ).strip().lower()
            == "submitted"
        )
        or (
            application is not None
            and str(
                application.status or ""
            ).strip().lower()
            == "applied"
        )
    )


def remove_discovered_job(
    job,
    *,
    reason,
    suppress=True,
):
    if suppress:
        suppress_discovered_job(
            job,
            reason=reason,
        )

    candidates = (
        AutoApplyCandidate.query
        .filter(
            AutoApplyCandidate.discovered_job_id
            == job.id
        )
        .all()
    )
    candidate_ids = [
        candidate.id
        for candidate in candidates
    ]
    package_ids = {
        candidate.application_package_id
        for candidate in candidates
        if candidate.application_package_id
    }
    application_ids = {
        candidate.application_id
        for candidate in candidates
        if candidate.application_id
    }
    packages = (
        ApplicationPackage.query
        .filter(
            db.or_(
                ApplicationPackage.discovered_job_id
                == job.id,
                ApplicationPackage.id.in_(package_ids)
                if package_ids
                else db.false(),
            )
        )
        .all()
    )
    packages_by_id = {
        package.id: package
        for package in packages
    }

    for package in packages:
        application_ids.add(
            package.application_id
        )

    applications = {
        application.id: application
        for application in (
            JobApplication.query
            .filter(
                JobApplication.id.in_(
                    application_ids
                )
            )
            .all()
            if application_ids
            else []
        )
    }
    preserved_package_ids = set()
    preserved_application_ids = set()

    for candidate in candidates:
        package = packages_by_id.get(
            candidate.application_package_id
        )
        application = applications.get(
            candidate.application_id
        )

        if _candidate_was_submitted(
            candidate,
            package,
            application,
        ):
            if package is not None:
                preserved_package_ids.add(
                    package.id
                )
            if application is not None:
                preserved_application_ids.add(
                    application.id
                )

    if candidate_ids:
        (
            ApplicationSubmissionAttempt.query
            .filter(
                ApplicationSubmissionAttempt
                .auto_apply_candidate_id
                .in_(candidate_ids)
            )
            .delete(
                synchronize_session=False
            )
        )

    for candidate in candidates:
        db.session.delete(candidate)

    db.session.flush()

    for package in packages:
        if (
            package.id in preserved_package_ids
            or str(
                package.status or ""
            ).strip().lower()
            == "submitted"
        ):
            package.discovered_job_id = None
            preserved_application_ids.add(
                package.application_id
            )
        else:
            db.session.delete(package)

    db.session.flush()

    for application in applications.values():
        status = str(
            application.status or ""
        ).strip()

        if (
            application.id
            in preserved_application_ids
            or status.lower() == "applied"
        ):
            continue

        remaining_packages = (
            ApplicationPackage.query
            .filter(
                ApplicationPackage.application_id
                == application.id
            )
            .count()
        )

        if (
            not remaining_packages
            and status.lower().startswith(
                "auto apply"
            )
        ):
            db.session.delete(application)

    job.matched_profiles.clear()
    db.session.delete(job)

    return {
        "discovered_jobs": 1,
        "candidates": len(candidates),
    }


def _url_variants(urls):
    variants = set()

    for value in urls:
        canonical_url = canonical_job_url(
            value
        )

        if not canonical_url:
            continue

        variants.add(canonical_url)

        if not canonical_url.endswith("/"):
            variants.add(
                f"{canonical_url}/"
            )

    return variants


def remove_job_records_for_urls(
    urls,
    *,
    reason,
    remove_cached=True,
):
    variants = _url_variants(urls)

    if not variants:
        return {
            "cached_jobs": 0,
            "discovered_jobs": 0,
            "candidates": 0,
        }

    jobs = (
        DiscoveredJob.query
        .filter(
            db.or_(
                DiscoveredJob.posting_url.in_(
                    variants
                ),
                DiscoveredJob.apply_url.in_(
                    variants
                ),
            )
        )
        .all()
    )
    stats = {
        "cached_jobs": 0,
        "discovered_jobs": 0,
        "candidates": 0,
    }

    for job in jobs:
        removed = remove_discovered_job(
            job,
            reason=reason,
        )
        stats["discovered_jobs"] += removed[
            "discovered_jobs"
        ]
        stats["candidates"] += removed[
            "candidates"
        ]

    if remove_cached:
        cached_jobs = (
            CachedSourceJob.query
            .filter(
                CachedSourceJob.posting_url.in_(
                    variants
                )
            )
            .all()
        )

        for cached_job in cached_jobs:
            db.session.delete(cached_job)

        stats["cached_jobs"] = len(
            cached_jobs
        )

    return stats


def purge_expired_job_records(
    *,
    now=None,
):
    aware_now = now or datetime.now(
        timezone.utc
    )
    naive_now = aware_now.replace(
        tzinfo=None
    )
    expired_cached_jobs = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.expires_at
            <= aware_now
        )
        .all()
    )
    expired_urls = {
        canonical_job_url(
            cached_job.posting_url
        )
        for cached_job in expired_cached_jobs
        if canonical_job_url(
            cached_job.posting_url
        )
    }
    stats = remove_job_records_for_urls(
        expired_urls,
        reason="Posting expired",
        remove_cached=True,
    )

    fallback_cutoff = (
        naive_now
        - timedelta(
            days=CACHE_RETENTION_DAYS
        )
    )
    fallback_jobs = (
        DiscoveredJob.query
        .filter(
            DiscoveredJob.discovered_at
            <= fallback_cutoff
        )
        .all()
    )

    for job in fallback_jobs:
        if job not in db.session.deleted:
            removed = remove_discovered_job(
                job,
                reason="Posting expired",
            )
            stats["discovered_jobs"] += removed[
                "discovered_jobs"
            ]
            stats["candidates"] += removed[
                "candidates"
            ]

    return stats


def postings_due_for_health_check(
    *,
    limit=HEALTH_CHECK_BATCH_SIZE,
    now=None,
):
    now = now or utcnow_naive()
    cache_state = db.session.get(
        JobLifecycleScanState,
        HEALTH_SCAN_STATE_NAME,
    )

    if cache_state is None:
        cache_state = JobLifecycleScanState(
            name=HEALTH_SCAN_STATE_NAME,
            cursor_id=0,
        )
        db.session.add(cache_state)

    discovered_state = db.session.get(
        JobLifecycleScanState,
        DISCOVERED_HEALTH_SCAN_STATE_NAME,
    )

    if discovered_state is None:
        discovered_state = JobLifecycleScanState(
            name=DISCOVERED_HEALTH_SCAN_STATE_NAME,
            cursor_id=0,
        )
        db.session.add(discovered_state)

    active_filter = (
        CachedSourceJob.expires_at
        > datetime.now(timezone.utc)
    )
    rows = (
        CachedSourceJob.query
        .filter(
            active_filter,
            CachedSourceJob.id
            > cache_state.cursor_id,
        )
        .order_by(CachedSourceJob.id.asc())
        .limit(limit)
        .all()
    )

    if len(rows) < limit:
        wrapped_rows = (
            CachedSourceJob.query
            .filter(
                active_filter,
                CachedSourceJob.id
                <= cache_state.cursor_id,
            )
            .order_by(CachedSourceJob.id.asc())
            .limit(limit - len(rows))
            .all()
        )
        rows.extend(wrapped_rows)

    if rows:
        cache_state.cursor_id = rows[-1].id
    else:
        cache_state.cursor_id = 0

    discovered_rows = (
        DiscoveredJob.query
        .filter(
            DiscoveredJob.id
            > discovered_state.cursor_id
        )
        .order_by(DiscoveredJob.id.asc())
        .limit(limit)
        .all()
    )

    if len(discovered_rows) < limit:
        wrapped_discovered_rows = (
            DiscoveredJob.query
            .filter(
                DiscoveredJob.id
                <= discovered_state.cursor_id
            )
            .order_by(DiscoveredJob.id.asc())
            .limit(
                limit
                - len(discovered_rows)
            )
            .all()
        )
        discovered_rows.extend(
            wrapped_discovered_rows
        )

    if discovered_rows:
        discovered_state.cursor_id = (
            discovered_rows[-1].id
        )
    else:
        discovered_state.cursor_id = 0

    rejected_rows = (
        DiscoveredJob.query
        .join(
            AutoApplyCandidate,
            AutoApplyCandidate.discovered_job_id
            == DiscoveredJob.id,
        )
        .filter(
            AutoApplyCandidate.status
            == "Rejected"
        )
        .order_by(
            AutoApplyCandidate.updated_at.desc(),
            AutoApplyCandidate.id.desc(),
        )
        .limit(100)
        .all()
    )
    rejected_url_keys = {
        job_url_key(row.posting_url)
        for row in rejected_rows
        if job_url_key(row.posting_url)
    }

    unique_urls = {}

    for row in (
        rejected_rows
        + discovered_rows
        + rows
    ):
        canonical_url = canonical_job_url(
            row.posting_url
        )

        if canonical_url:
            unique_urls.setdefault(
                job_url_key(canonical_url),
                canonical_url,
            )

    health_rows = {
        health.url_key: health
        for health in (
            JobPostingHealth.query
            .filter(
                JobPostingHealth.url_key.in_(
                    list(unique_urls)
                )
            )
            .all()
            if unique_urls
            else []
        )
    }
    due = []

    for url_key, posting_url in unique_urls.items():
        health = health_rows.get(url_key)

        if health is not None and health.status == "Closed":
            continue

        if (
            health is not None
            and health.last_checked_at is not None
            and health.last_checked_at
            > (
                now
                - (
                    REJECTED_HEALTH_RECHECK_INTERVAL
                    if url_key
                    in rejected_url_keys
                    else HEALTH_RECHECK_INTERVAL
                )
            )
        ):
            continue

        due.append(posting_url)

        if len(due) >= limit:
            break

    return due


def _himalayas_redirected_to_jobs_root(
    original_url,
    final_url,
):
    original = urlsplit(
        canonical_job_url(original_url)
    )
    final = urlsplit(
        canonical_job_url(final_url)
    )
    original_host = original.hostname or ""
    final_host = final.hostname or ""

    return (
        original_host.removeprefix("www.")
        == "himalayas.app"
        and original.path.rstrip("/")
        != "/jobs"
        and final_host.removeprefix("www.")
        == "himalayas.app"
        and final.path.rstrip("/")
        == "/jobs"
    )


def check_job_posting(posting_url):
    checked_at = utcnow_naive()

    try:
        response = requests.get(
            posting_url,
            allow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; "
                    "JobfinitumJobHealth/1.0)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
    except requests.RequestException as error:
        return {
            "posting_url": posting_url,
            "status": "Unknown",
            "reason": str(error)[:255],
            "final_url": None,
            "http_status": None,
            "checked_at": checked_at,
        }

    final_url = canonical_job_url(
        response.url
    )

    if response.status_code in {404, 410}:
        return {
            "posting_url": posting_url,
            "status": "Closed",
            "reason": (
                "Posting returned HTTP "
                f"{response.status_code}"
            ),
            "final_url": final_url,
            "http_status": response.status_code,
            "checked_at": checked_at,
        }

    if _himalayas_redirected_to_jobs_root(
        posting_url,
        final_url,
    ):
        return {
            "posting_url": posting_url,
            "status": "Closed",
            "reason": (
                "Himalayas redirected the posting "
                "to its jobs index"
            ),
            "final_url": final_url,
            "http_status": response.status_code,
            "checked_at": checked_at,
        }

    if response.status_code >= 400:
        return {
            "posting_url": posting_url,
            "status": "Unknown",
            "reason": (
                "Posting check returned HTTP "
                f"{response.status_code}"
            ),
            "final_url": final_url,
            "http_status": response.status_code,
            "checked_at": checked_at,
        }

    soup = BeautifulSoup(
        response.text[:2_000_000],
        "html.parser",
    )
    visible_text = " ".join(
        soup.stripped_strings
    )[:250_000]

    for pattern in CLOSED_PAGE_PATTERNS:
        if pattern.search(visible_text):
            return {
                "posting_url": posting_url,
                "status": "Closed",
                "reason": (
                    "Posting page says it is no "
                    "longer accepting applications"
                ),
                "final_url": final_url,
                "http_status": response.status_code,
                "checked_at": checked_at,
            }

    return {
        "posting_url": posting_url,
        "status": "Active",
        "reason": None,
        "final_url": final_url,
        "http_status": response.status_code,
        "checked_at": checked_at,
    }


def record_job_health_result(result):
    posting_url = canonical_job_url(
        result.get("posting_url")
    )
    url_key = job_url_key(posting_url)

    if not posting_url or not url_key:
        return {
            "cached_jobs": 0,
            "discovered_jobs": 0,
            "candidates": 0,
        }

    health = db.session.get(
        JobPostingHealth,
        url_key,
    )

    if health is None:
        health = JobPostingHealth(
            url_key=url_key,
            posting_url=posting_url,
        )
        db.session.add(health)

    result_status = str(
        result.get("status")
        or "Unknown"
    )

    if health.status == "Closed":
        result_status = "Closed"

    health.posting_url = posting_url
    health.status = result_status
    health.reason = result.get("reason")
    health.final_url = canonical_job_url(
        result.get("final_url")
    ) or None
    health.http_status = result.get(
        "http_status"
    )
    health.last_checked_at = (
        result.get("checked_at")
        or utcnow_naive()
    )

    if result_status == "Unknown":
        health.consecutive_failures = (
            int(
                health.consecutive_failures
                or 0
            )
            + 1
        )
    else:
        health.consecutive_failures = 0

    if result_status != "Closed":
        return {
            "cached_jobs": 0,
            "discovered_jobs": 0,
            "candidates": 0,
        }

    health.closed_at = (
        health.closed_at
        or utcnow_naive()
    )

    return remove_job_records_for_urls(
        {posting_url},
        reason=health.reason or "Posting closed",
        remove_cached=True,
    )
