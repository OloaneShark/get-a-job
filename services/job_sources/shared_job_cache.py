
import hashlib
import json
from datetime import date, datetime, timedelta, timezone

from models import (
    CachedSourceJob,
    JobSourceCacheState,
    db,
)


CACHE_RETENTION_DAYS = 60
DEFAULT_SOURCE_REFRESH_INTERVAL = timedelta(hours=6)
MINIMUM_SOURCE_REFRESH_INTERVAL = timedelta(hours=1)


def utc_now():
    return datetime.now(timezone.utc)


def ensure_utc(value):
    if value is None:
        return None

    if isinstance(value, date) and not isinstance(
        value,
        datetime,
    ):
        value = datetime.combine(
            value,
            datetime.min.time(),
        )

    if not isinstance(value, datetime):
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def json_safe(value):
    if isinstance(value, datetime):
        normalized = ensure_utc(value)

        return {
            "__jobfinitum_type__": "datetime",
            "value": normalized.isoformat(),
        }

    if isinstance(value, date):
        return {
            "__jobfinitum_type__": "date",
            "value": value.isoformat(),
        }

    if isinstance(value, dict):
        return {
            str(key): json_safe(item)
            for key, item
            in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [
            json_safe(item)
            for item in value
        ]

    if value is None or isinstance(
        value,
        (str, int, float, bool),
    ):
        return value

    return str(value)


def restore_json(value):
    if isinstance(value, dict):
        marker = value.get(
            "__jobfinitum_type__"
        )

        if (
            marker == "datetime"
            and "value" in value
        ):
            raw_value = value.get(
                "value"
            )

            try:
                parsed = datetime.fromisoformat(
                    str(raw_value)
                )
            except (
                TypeError,
                ValueError,
            ):
                return raw_value

            return ensure_utc(
                parsed
            )

        if (
            marker == "date"
            and "value" in value
        ):
            try:
                return date.fromisoformat(
                    str(
                        value.get(
                            "value"
                        )
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                return value.get(
                    "value"
                )

        return {
            key: restore_json(item)
            for key, item
            in value.items()
        }

    if isinstance(value, list):
        return [
            restore_json(item)
            for item in value
        ]

    return value


def normalized_text(value):
    return str(
        value or ""
    ).strip()


def canonical_posting_url(value):
    return (
        normalized_text(value)
        .split("#", 1)[0]
        .rstrip("/")
    )


def cache_key_for_job(job):
    external_id = normalized_text(
        job.get("external_id")
    )

    if external_id:
        raw_key = (
            "external:"
            + external_id
        )
    else:
        posting_url = (
            canonical_posting_url(
                job.get(
                    "posting_url"
                )
            )
        )

        if not posting_url:
            return None

        raw_key = (
            "url:"
            + posting_url
        )

    return hashlib.sha256(
        raw_key.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def parse_published_at(value):
    parsed = ensure_utc(
        value
    )

    if parsed is not None:
        return parsed

    text = normalized_text(
        value
    )

    if not text:
        return None

    if text.endswith("Z"):
        text = (
            text[:-1]
            + "+00:00"
        )

    try:
        parsed = datetime.fromisoformat(
            text
        )
    except ValueError:
        parsed = None

    if parsed is not None:
        return ensure_utc(
            parsed
        )

    for format_string in (
        "%b %d, %Y",
        "%B %d, %Y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(
                text,
                format_string,
            )
        except ValueError:
            continue

        return parsed.replace(
            tzinfo=timezone.utc
        )

    return None


def sane_published_at(
    value,
    *,
    now=None,
):
    now = ensure_utc(
        now
    ) or utc_now()

    parsed = parse_published_at(
        value
    )

    if parsed is None:
        return None

    # A future posting date is usually bad source metadata.
    # Do not let it artificially extend retention.
    if parsed > (
        now
        + timedelta(days=1)
    ):
        return None

    return parsed


def expiration_for_job(
    *,
    published_at,
    first_seen_at,
):
    anchor = (
        ensure_utc(
            published_at
        )
        or ensure_utc(
            first_seen_at
        )
        or utc_now()
    )

    return (
        anchor
        + timedelta(
            days=CACHE_RETENTION_DAYS
        )
    )


def build_profile_signature(
    profiles,
):
    fields = (
        "id",
        "keywords",
        "locations",
        "employment_types",
        "workplace_types",
        "experience_levels",
        "remote_scope",
        "remote_only",
        "visa_preference",
        "visa_required",
        "overseas_applicant_preference",
        "minimum_salary",
        "maximum_posting_age_days",
        "active",
    )

    profile_data = []

    for profile in profiles:
        item = {}

        for field in fields:
            value = getattr(
                profile,
                field,
                None,
            )

            if isinstance(
                value,
                str,
            ):
                value = value.strip()

            item[field] = value

        profile_data.append(
            item
        )

    profile_data.sort(
        key=lambda item: (
            item.get("id")
            if item.get("id")
            is not None
            else -1,
            str(
                item.get(
                    "keywords"
                )
                or ""
            ),
        )
    )

    serialized = json.dumps(
        profile_data,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(
        serialized.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def source_refresh_interval(
    source,
):
    interval = getattr(
        source,
        "db_cache_refresh_interval",
        None,
    )

    if not isinstance(
        interval,
        timedelta,
    ):
        interval = getattr(
            source,
            "cache_duration",
            None,
        )

    if not isinstance(
        interval,
        timedelta,
    ):
        interval = (
            DEFAULT_SOURCE_REFRESH_INTERVAL
        )

    if interval <= timedelta(0):
        interval = (
            DEFAULT_SOURCE_REFRESH_INTERVAL
        )

    return max(
        interval,
        MINIMUM_SOURCE_REFRESH_INTERVAL,
    )


def state_snapshot(state):
    if state is None:
        return None

    return {
        "source_type": state.source_type,
        "source_name": state.source_name,
        "profile_signature": (
            state.profile_signature
        ),
        "cache_scope": (
            state.cache_scope
        ),
        "last_refresh_attempt_at": (
            ensure_utc(
                state.last_refresh_attempt_at
            )
        ),
        "last_successful_refresh_at": (
            ensure_utc(
                state.last_successful_refresh_at
            )
        ),
        "last_refresh_status": (
            state.last_refresh_status
        ),
        "last_refresh_error": (
            state.last_refresh_error
        ),
        "cached_job_count": (
            state.cached_job_count
            or 0
        ),
    }


def load_source_cache_bundle(
    source_type,
):
    source_type = normalized_text(
        source_type
    ).lower()

    if not source_type:
        return None, []

    state = db.session.get(
        JobSourceCacheState,
        source_type,
    )

    now = utc_now()

    rows = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.source_type
            == source_type,
            CachedSourceJob.expires_at
            > now,
        )
        .order_by(
            CachedSourceJob
            .published_at
            .desc()
            .nullslast(),
            CachedSourceJob
            .first_seen_at
            .desc(),
        )
        .all()
    )

    jobs = [
        restore_json(
            row.job_payload
        )
        for row in rows
        if isinstance(
            row.job_payload,
            dict,
        )
    ]

    return (
        state_snapshot(
            state
        ),
        jobs,
    )


def cache_state_is_fresh(
    state,
    *,
    profile_signature,
    refresh_interval,
    now=None,
):
    if not state:
        return False

    if (
        state.get(
            "profile_signature"
        )
        != profile_signature
    ):
        return False

    last_success = ensure_utc(
        state.get(
            "last_successful_refresh_at"
        )
    )

    if last_success is None:
        return False

    now = ensure_utc(
        now
    ) or utc_now()

    return (
        now - last_success
        < refresh_interval
    )


def purge_expired_cached_jobs(
    *,
    now=None,
):
    now = ensure_utc(
        now
    ) or utc_now()

    expired_rows = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.expires_at
            <= now
        )
        .all()
    )

    count = len(
        expired_rows
    )

    for row in expired_rows:
        db.session.delete(
            row
        )

    return count


def prepared_job_list(
    source,
    prepare_result,
):
    if isinstance(
        prepare_result,
        list,
    ):
        return list(
            prepare_result
        )

    prepared = getattr(
        source,
        "_prepared_jobs",
        None,
    )

    if isinstance(
        prepared,
        list,
    ):
        return list(
            prepared
        )

    return None


def upsert_cached_source_jobs(
    *,
    source_type,
    source_name,
    jobs,
    profile_signature,
    cache_scope,
    refreshed_at=None,
):
    source_type = normalized_text(
        source_type
    ).lower()
    source_name = (
        normalized_text(
            source_name
        )
        or source_type
    )
    refreshed_at = (
        ensure_utc(
            refreshed_at
        )
        or utc_now()
    )

    if not source_type:
        raise ValueError(
            "A source_type is required."
        )

    existing_rows = (
        CachedSourceJob.query
        .filter_by(
            source_type=source_type
        )
        .all()
    )

    existing_by_key = {
        row.cache_key: row
        for row in existing_rows
    }

    unique_jobs = {}

    for job in jobs or []:
        if not isinstance(
            job,
            dict,
        ):
            continue

        cache_key = (
            cache_key_for_job(
                job
            )
        )

        if not cache_key:
            continue

        unique_jobs[
            cache_key
        ] = dict(job)

    created = 0
    updated = 0
    skipped_expired = 0
    skipped_invalid = 0

    for (
        cache_key,
        job,
    ) in unique_jobs.items():
        posting_url = (
            canonical_posting_url(
                job.get(
                    "posting_url"
                )
            )
        )

        title = normalized_text(
            job.get(
                "position_title"
            )
        )
        company = normalized_text(
            job.get(
                "company_name"
            )
        )

        if (
            not posting_url
            or not title
            or not company
        ):
            skipped_invalid += 1
            continue

        existing = (
            existing_by_key.get(
                cache_key
            )
        )

        first_seen_at = (
            ensure_utc(
                existing.first_seen_at
            )
            if existing
            else refreshed_at
        )

        new_published_at = (
            sane_published_at(
                job.get(
                    "published_at"
                ),
                now=refreshed_at,
            )
        )

        existing_published_at = (
            ensure_utc(
                existing.published_at
            )
            if existing
            else None
        )

        if (
            existing_published_at
            is not None
            and new_published_at
            is not None
        ):
            # Keep the earliest known original posting date.
            effective_published_at = min(
                existing_published_at,
                new_published_at,
            )
        else:
            effective_published_at = (
                existing_published_at
                or new_published_at
            )

        expires_at = (
            expiration_for_job(
                published_at=(
                    effective_published_at
                ),
                first_seen_at=(
                    first_seen_at
                ),
            )
        )

        if expires_at <= refreshed_at:
            skipped_expired += 1

            if existing is not None:
                db.session.delete(
                    existing
                )
                existing_by_key.pop(
                    cache_key,
                    None,
                )

            continue

        job[
            "published_at"
        ] = effective_published_at

        payload = json_safe(
            job
        )

        if existing is None:
            row = CachedSourceJob(
                source_type=source_type,
                source_name=source_name,
                cache_key=cache_key,
                external_id=(
                    normalized_text(
                        job.get(
                            "external_id"
                        )
                    )
                    or None
                ),
                company_name=company,
                position_title=title,
                posting_url=posting_url,
                published_at=(
                    effective_published_at
                ),
                first_seen_at=(
                    first_seen_at
                ),
                last_seen_at=(
                    refreshed_at
                ),
                expires_at=(
                    expires_at
                ),
                job_payload=payload,
            )

            db.session.add(
                row
            )
            existing_by_key[
                cache_key
            ] = row
            created += 1

        else:
            existing.source_name = (
                source_name
            )
            existing.external_id = (
                normalized_text(
                    job.get(
                        "external_id"
                    )
                )
                or None
            )
            existing.company_name = (
                company
            )
            existing.position_title = (
                title
            )
            existing.posting_url = (
                posting_url
            )
            existing.published_at = (
                effective_published_at
            )
            existing.last_seen_at = (
                refreshed_at
            )
            existing.expires_at = (
                expires_at
            )
            existing.job_payload = (
                payload
            )
            updated += 1

    state = db.session.get(
        JobSourceCacheState,
        source_type,
    )

    if state is None:
        state = JobSourceCacheState(
            source_type=source_type,
            source_name=source_name,
        )
        db.session.add(
            state
        )

    active_count = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.source_type
            == source_type,
            CachedSourceJob.expires_at
            > refreshed_at,
        )
        .count()
    )

    state.source_name = (
        source_name
    )
    state.profile_signature = (
        profile_signature
    )
    state.cache_scope = (
        cache_scope
    )
    state.last_refresh_attempt_at = (
        refreshed_at
    )
    state.last_successful_refresh_at = (
        refreshed_at
    )
    state.last_refresh_status = (
        "Completed"
    )
    state.last_refresh_error = None
    state.cached_job_count = (
        active_count
    )
    state.updated_at = (
        refreshed_at
    )

    return {
        "received": len(
            unique_jobs
        ),
        "created": created,
        "updated": updated,
        "active": active_count,
        "skipped_expired": (
            skipped_expired
        ),
        "skipped_invalid": (
            skipped_invalid
        ),
        "retention_days": (
            CACHE_RETENTION_DAYS
        ),
    }


def record_source_cache_failure(
    *,
    source_type,
    source_name,
    error,
    attempted_at=None,
):
    source_type = normalized_text(
        source_type
    ).lower()
    source_name = (
        normalized_text(
            source_name
        )
        or source_type
    )
    attempted_at = (
        ensure_utc(
            attempted_at
        )
        or utc_now()
    )

    state = db.session.get(
        JobSourceCacheState,
        source_type,
    )

    if state is None:
        state = JobSourceCacheState(
            source_type=source_type,
            source_name=source_name,
        )
        db.session.add(
            state
        )

    state.source_name = (
        source_name
    )
    state.last_refresh_attempt_at = (
        attempted_at
    )
    state.last_refresh_status = (
        "Failed"
    )
    state.last_refresh_error = (
        str(error)
    )[:4000]
    state.updated_at = (
        attempted_at
    )
