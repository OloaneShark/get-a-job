
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import inspect
from sqlalchemy.exc import DBAPIError

from apscheduler.schedulers.background import BackgroundScheduler

from models import (
    DiscoveredJob,
    JobSearchProfile,
    JobSourceCompany,
    db
)
from services.job_sources.registry import create_source
from services.job_sources.job_match_service import (
    collect_match_diagnostics,
    format_match_diagnostics,
    job_matches_profile,
)
from services.job_sources.shared_job_cache import (
    build_profile_signature,
    cache_state_is_fresh,
    load_source_cache_bundle,
    prepared_job_list,
    purge_expired_cached_jobs,
    record_source_cache_failure,
    source_refresh_interval,
    upsert_cached_source_jobs,
)
from services.job_sources.configured_source_cache import (
    CONFIGURED_SOURCE_REFRESH_INTERVAL,
    CONFIGURED_SOURCE_REFRESH_WORKERS,
    configured_cache_namespace,
    configured_cache_signature,
    iter_configured_source_refreshes,
    load_configured_cache_bundles,
    prune_missing_configured_jobs,
)
from services.job_sources.utils import (
    build_job_fingerprint,
    cross_source_jobs_match,
    normalize_identity_text,
)
from services.job_sources.discovery.common_crawl_discovery import (
    run_common_crawl_discovery,
)


scheduler = BackgroundScheduler(
    timezone="UTC"
)


AUTOMATIC_DISCOVERY_JOB_ID = (
    "automatic_job_source_discovery"
)
_automatic_discovery_lock = threading.Lock()
_automatic_discovery_status = {
    "run_id": None,
    "state": "idle",
    "message": (
        "Automatic discovery has not been run "
        "in this process."
    ),
    "started_at": None,
    "completed_at": None,
    "error": None,
    "results": None,
}


def environment_flag(name, default=False):
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def source_debug_enabled():
    return environment_flag(
        "JOB_SOURCE_DEBUG",
        default=False,
    )


def should_print_match_summary(
    diagnostics,
):
    return (
        diagnostics["evaluated"] > 0
        and (
            diagnostics["matched"] > 0
            or source_debug_enabled()
        )
    )


#These sources expose one global job feed and do not require
#individual company configurations in JobSourceCompany.
#ALSO I HATE WORKING WITH ASHBY AND GREENHOUSE AND LEVER SO MUCH
#WHY CANT IT JUST BE MORE SIMPLE LIKE THIS
GLOBAL_SOURCE_TYPES = [
    "remote_ok",
    "we_work_remotely",
    "remotive",
    "himalayas",
    "jobicy",
    "arbeitnow",
    "japan_dev",
    "tokyo_dev",
    "adzuna",
    "jooble",
    "usajobs",
    "the_muse",
    "python_org",
    "hacker_news_jobs",
    "cncf_gitjobs",
    "remote_first_jobs",
    "y_combinator",
    "ai_dev_jobs",
    "green_japan",
    "amazon_jobs",
    "apple_jobs",
]


def parse_profile_values(value):
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(
            r"[\n,]+",
            value,
        )
        if item.strip()
    ]


DATABASE_DISCONNECT_MARKERS = (
    "ssl connection has been closed unexpectedly",
    "server closed the connection unexpectedly",
    "connection already closed",
    "connection is closed",
    "connection not open",
    "terminating connection",
    "connection reset by peer",
    "could not receive data from server",
    "broken pipe",
)


def snapshot_model(instance):
    return SimpleNamespace(**{
        attribute.key: getattr(
            instance,
            attribute.key,
        )
        for attribute
        in inspect(instance).mapper.column_attrs
    })


def database_error_is_disconnect(error):
    if (
        isinstance(error, DBAPIError)
        and getattr(
            error,
            "connection_invalidated",
            False,
        )
    ):
        return True

    original_error = getattr(
        error,
        "orig",
        None,
    )
    message = (
        f"{error} {original_error or ''}"
        .lower()
    )

    return any(
        marker in message
        for marker
        in DATABASE_DISCONNECT_MARKERS
    )


def run_database_transaction(
    operation_name,
    callback,
    max_attempts=2,
):
    last_error = None

    for attempt in range(
        1,
        max_attempts + 1,
    ):
        # Remove any session that may still own a
        # connection from before the long crawl.
        db.session.remove()

        try:
            result = callback()
            db.session.commit()

        except Exception as error:
            last_error = error

            try:
                db.session.rollback()
            except Exception:
                pass

            db.session.remove()

            should_retry = (
                attempt < max_attempts
                and database_error_is_disconnect(
                    error
                )
            )

            if not should_retry:
                raise

            print(
                "DATABASE CONNECTION RETRY | "
                f"Operation: {operation_name} | "
                f"Attempt: {attempt + 1}/"
                f"{max_attempts} | "
                f"Error: {error}"
            )

            # The failed transaction is gone. Dispose
            # the stale pool so the retry checks out a
            # newly established PostgreSQL connection.
            db.engine.dispose()
            continue

        db.session.remove()
        return result

    raise last_error


def load_scheduler_snapshots():
    def load():
        profiles = (
            JobSearchProfile.query
            .filter_by(active=True)
            .all()
        )
        source_configs = (
            JobSourceCompany.query
            .filter_by(is_active=True)
            .order_by(
                JobSourceCompany
                .source_type.asc(),
                JobSourceCompany
                .company_name.asc(),
            )
            .all()
        )

        return (
            [
                snapshot_model(profile)
                for profile in profiles
            ],
            [
                snapshot_model(source_config)
                for source_config
                in source_configs
            ],
        )

    return run_database_transaction(
        "load scheduler configuration",
        load,
    )


def apply_source_status_updates(
    source_status_updates,
):
    for update in source_status_updates:
        source_config = db.session.get(
            JobSourceCompany,
            update["id"],
        )

        if source_config is None:
            continue

        source_config.last_checked_at = (
            update["last_checked_at"]
        )
        source_config.last_check_status = (
            update["last_check_status"]
        )
        source_config.last_check_error = (
            update["last_check_error"]
        )


def persist_profile_results(
    profile_id,
    jobs,
    matched_count,
    source_errors,
    source_status_updates,
):
    def persist():
        profile = db.session.get(
            JobSearchProfile,
            profile_id,
        )

        if (
            profile is None
            or not profile.active
        ):
            return {
                "profile_name": None,
                "saved_count": 0,
                "skipped": True,
            }

        apply_source_status_updates(
            source_status_updates
        )

        saved_count = save_discovered_jobs(
            profile,
            jobs,
        )

        profile.last_searched_at = (
            datetime.now(
                timezone.utc
            )
        )
        profile.last_result_count = (
            saved_count
        )

        if source_errors:
            profile.last_search_status = (
                "Completed With Errors"
            )
            profile.last_search_error = (
                "\n".join(
                    source_errors
                )
            )
        else:
            profile.last_search_status = (
                "Completed"
            )
            profile.last_search_error = None

        return {
            "profile_name": profile.name,
            "matched_count": matched_count,
            "saved_count": saved_count,
            "skipped": False,
        }

    return run_database_transaction(
        (
            "save search results for "
            f"profile {profile_id}"
        ),
        persist,
    )


def persist_profile_failure(
    profile_id,
    error,
):
    def persist():
        profile = db.session.get(
            JobSearchProfile,
            profile_id,
        )

        if profile is None:
            return None

        profile.last_searched_at = (
            datetime.now(
                timezone.utc
            )
        )
        profile.last_result_count = 0
        profile.last_search_status = (
            "Failed"
        )
        profile.last_search_error = (
            str(error)
        )

        return profile.name

    return run_database_transaction(
        (
            "record search failure for "
            f"profile {profile_id}"
        ),
        persist,
    )


def save_discovered_jobs(
    profile,
    jobs,
):
    saved_count = 0

    existing_jobs = (
        DiscoveredJob.query
        .filter(
            DiscoveredJob.user_id
            == profile.user_id
        )
        .all()
    )

    by_source_external = {}
    by_fingerprint = {}
    by_posting_url = {}
    by_company = {}

    def canonical_posting_url(value):
        return (
            str(value or "")
            .strip()
            .rstrip("/")
        )

    def index_job(indexed_job):
        indexed_source = str(
            getattr(
                indexed_job,
                "source",
                None,
            )
            or "Unknown"
        ).strip() or "Unknown"

        indexed_external_id = str(
            getattr(
                indexed_job,
                "external_id",
                None,
            )
            or ""
        ).strip()

        if indexed_external_id:
            by_source_external[
                (
                    indexed_source,
                    indexed_external_id,
                )
            ] = indexed_job

        indexed_fingerprint = str(
            getattr(
                indexed_job,
                "fingerprint",
                None,
            )
            or ""
        ).strip()

        if indexed_fingerprint:
            by_fingerprint[
                indexed_fingerprint
            ] = indexed_job

        indexed_posting_url = (
            canonical_posting_url(
                getattr(
                    indexed_job,
                    "posting_url",
                    None,
                )
            )
        )

        if indexed_posting_url:
            by_posting_url[
                indexed_posting_url
            ] = indexed_job

        company_identity = (
            normalize_identity_text(
                getattr(
                    indexed_job,
                    "company_name",
                    None,
                )
            )
        )

        if company_identity:
            by_company.setdefault(
                company_identity,
                [],
            ).append(
                indexed_job
            )

    for existing_job in existing_jobs:
        index_job(
            existing_job
        )

    for job in jobs:
        posting_url = job.get(
            "posting_url"
        )

        if not posting_url:
            continue

        source = str(
            job.get("source")
            or "Unknown"
        ).strip() or "Unknown"

        external_id = str(
            job.get("external_id")
            or ""
        ).strip() or None

        fingerprint = (
            build_job_fingerprint(
                job.get("company_name"),
                job.get("position_title"),
                job.get("location"),
                posting_url,
            )
        )

        canonical_url = (
            canonical_posting_url(
                posting_url
            )
        )

        existing_job = None

        if external_id:
            existing_job = (
                by_source_external.get(
                    (
                        source,
                        external_id,
                    )
                )
            )

        if existing_job is None:
            company_identity = (
                normalize_identity_text(
                    job.get(
                        "company_name"
                    )
                )
            )

            for candidate in (
                by_company.get(
                    company_identity,
                    []
                )
            ):
                if cross_source_jobs_match(
                    candidate,
                    job,
                ):
                    existing_job = candidate
                    break

        if existing_job is None:
            existing_job = (
                by_fingerprint.get(
                    fingerprint
                )
                or by_posting_url.get(
                    canonical_url
                )
            )

        if existing_job:
            if (
                profile
                not in existing_job
                .matched_profiles
            ):
                existing_job.matched_profiles.append(
                    profile
                )

            continue

        discovered_job = DiscoveredJob(
            user_id=profile.user_id,
            search_profile_id=profile.id,
            source=source,
            external_id=external_id,
            company_name=(
                job.get("company_name")
                or "Unknown Company"
            ),
            position_title=(
                job.get("position_title")
                or "Untitled Position"
            ),
            location=job.get("location"),
            employment_type=job.get(
                "employment_type"
            ),
            salary=job.get("salary"),
            visa_sponsorship=(
                job.get("visa_sponsorship")
                or "Unknown"
            ),
            posting_url=posting_url,
            apply_url=(
                job.get("apply_url")
                or posting_url
            ),
            job_description=job.get(
                "job_description"
            ),
            recruiter_name=job.get(
                "recruiter_name"
            ),
            recruiter_email=job.get(
                "recruiter_email"
            ),
            recruiter_contact_url=job.get(
                "recruiter_contact_url"
            ),
            recruiter_contact_source=job.get(
                "recruiter_contact_source"
            ),
            fingerprint=fingerprint,
        )

        discovered_job.matched_profiles.append(
            profile
        )

        db.session.add(
            discovered_job
        )
        index_job(
            discovered_job
        )
        saved_count += 1

    return saved_count


def create_global_sources():
    return {
        source_type: create_source(
            source_type
        )
        for source_type
        in GLOBAL_SOURCE_TYPES
    }


def persist_global_source_cache(
    source,
    jobs,
    profile_signature,
    cache_scope,
):
    source_type = (
        source.source_type
        or ""
    ).strip().lower()

    def persist():
        return upsert_cached_source_jobs(
            source_type=source_type,
            source_name=(
                source.source_name
            ),
            jobs=jobs,
            profile_signature=(
                profile_signature
            ),
            cache_scope=(
                cache_scope
            ),
        )

    stats = run_database_transaction(
        (
            "persist shared job cache for "
            f"{source_type}"
        ),
        persist,
    )

    print(
        "GLOBAL SOURCE DB CACHE WRITE | "
        f"Source: {source.source_name} | "
        f"Received: {stats['received']} | "
        f"Created: {stats['created']} | "
        f"Updated: {stats['updated']} | "
        f"Active: {stats['active']} | "
        f"Expired skipped: "
        f"{stats['skipped_expired']} | "
        f"Invalid skipped: "
        f"{stats['skipped_invalid']} | "
        f"Retention: "
        f"{stats['retention_days']} days"
    )

    return stats


def record_global_source_cache_failure(
    source,
    error,
):
    def persist():
        record_source_cache_failure(
            source_type=(
                source.source_type
            ),
            source_name=(
                source.source_name
            ),
            error=error,
        )

    try:
        run_database_transaction(
            (
                "record shared job cache "
                f"failure for "
                f"{source.source_type}"
            ),
            persist,
        )

    except Exception as cache_error:
        print(
            "GLOBAL SOURCE DB CACHE "
            "FAILURE STATUS ERROR | "
            f"Source: "
            f"{source.source_name} | "
            f"Error: {cache_error}"
        )


def load_global_source_cache(
    source,
):
    def load():
        return load_source_cache_bundle(
            source.source_type
        )

    return run_database_transaction(
        (
            "load shared job cache for "
            f"{source.source_type}"
        ),
        load,
    )


def prepare_global_sources(
    profiles,
    global_sources,
):
    profile_signature = (
        build_profile_signature(
            profiles
        )
    )

    def purge():
        return (
            purge_expired_cached_jobs()
        )

    purged_count = (
        run_database_transaction(
            "purge expired shared job cache",
            purge,
        )
    )

    if purged_count:
        print(
            "GLOBAL SOURCE DB CACHE PURGE | "
            f"Removed: {purged_count}"
        )

    for source_type in GLOBAL_SOURCE_TYPES:
        source = global_sources[
            source_type
        ]

        # Per-run state lives on the source instance so the existing
        # scheduler call graph does not need a separate global object.
        source._db_cache_profile_signature = (
            profile_signature
        )
        source._db_cache_mode = (
            "network"
        )
        source._db_cached_jobs = []
        source._db_cache_accumulator = {}
        source._db_cache_errors = []

        refresh_interval = (
            source_refresh_interval(
                source
            )
        )

        try:
            (
                cache_state,
                cached_jobs,
            ) = load_global_source_cache(
                source
            )

        except Exception as error:
            cache_state = None
            cached_jobs = []

            print(
                "GLOBAL SOURCE DB CACHE "
                "LOAD ERROR | "
                f"Source: "
                f"{source.source_name} | "
                f"Error: {error}"
            )

        if cache_state_is_fresh(
            cache_state,
            profile_signature=(
                profile_signature
            ),
            refresh_interval=(
                refresh_interval
            ),
        ):
            source._db_cache_mode = (
                "database"
            )
            source._db_cached_jobs = list(
                cached_jobs
            )

            print(
                "GLOBAL SOURCE DB CACHE HIT | "
                f"Source: "
                f"{source.source_name} | "
                f"Jobs: "
                f"{len(cached_jobs)} | "
                f"Refresh interval: "
                f"{refresh_interval}"
            )
            continue

        prepare = getattr(
            source,
            "prepare",
            None,
        )

        if not callable(prepare):
            print(
                "GLOBAL SOURCE DB CACHE MISS | "
                f"Source: "
                f"{source.source_name} | "
                "No shared prepare() method; "
                "this refresh will collect the "
                "union of profile matches."
            )
            continue

        try:
            print(
                "GLOBAL SOURCE PREPARE | "
                f"Preparing shared "
                f"{source.source_name} feed "
                f"for {len(profiles)} "
                "active profiles."
            )

            prepare_result = (
                prepare(profiles)
            )

            prepared_jobs = (
                prepared_job_list(
                    source,
                    prepare_result,
                )
            )

            if prepared_jobs is None:
                print(
                    "GLOBAL SOURCE DB CACHE "
                    "PREPARE FALLBACK | "
                    f"Source: "
                    f"{source.source_name} | "
                    "prepare() did not expose a "
                    "normalized job list; profile "
                    "matches will seed the cache."
                )
                continue

            persist_global_source_cache(
                source,
                prepared_jobs,
                profile_signature,
                "prepared_feed",
            )

            source._db_cache_mode = (
                "prepared"
            )

        except Exception as error:
            source._db_cache_errors.append(
                str(error)
            )

            # Keep the scheduler alive. The source's search()
            # method may retry for an individual profile, and
            # the failure will still be recorded normally.
            print(
                "GLOBAL SOURCE PREPARE ERROR | "
                f"{source.source_name}: "
                f"{error}"
            )


def finalize_global_source_db_cache(
    global_sources,
):
    for source_type in GLOBAL_SOURCE_TYPES:
        source = global_sources[
            source_type
        ]

        mode = getattr(
            source,
            "_db_cache_mode",
            None,
        )

        if mode in {
            "database",
            "prepared",
        }:
            continue

        errors = list(
            getattr(
                source,
                "_db_cache_errors",
                [],
            )
            or []
        )

        if errors:
            record_global_source_cache_failure(
                source,
                "\n".join(
                    errors
                ),
            )
            continue

        accumulator = getattr(
            source,
            "_db_cache_accumulator",
            {},
        )

        jobs = list(
            accumulator.values()
        )

        try:
            persist_global_source_cache(
                source,
                jobs,
                getattr(
                    source,
                    "_db_cache_profile_signature",
                    None,
                ),
                "matched_union",
            )

        except Exception as error:
            record_global_source_cache_failure(
                source,
                error,
            )

            print(
                "GLOBAL SOURCE DB CACHE "
                "FINALIZE ERROR | "
                f"Source: "
                f"{source.source_name} | "
                f"Error: {error}"
            )



def prepare_configured_source_caches(
    profiles,
    source_configs,
):
    if not source_configs:
        return {}

    profile_signature = (
        build_profile_signature(
            profiles
        )
    )

    config_by_id = {
        source_config.id: source_config
        for source_config
        in source_configs
    }

    namespace_by_id = {
        source_config.id: (
            configured_cache_namespace(
                source_config
            )
        )
        for source_config
        in source_configs
    }

    signature_by_id = {
        source_config.id: (
            configured_cache_signature(
                source_config,
                profile_signature,
            )
        )
        for source_config
        in source_configs
    }

    namespaces = list(
        namespace_by_id.values()
    )

    def load_all():
        return (
            load_configured_cache_bundles(
                namespaces
            )
        )

    try:
        bundles = (
            run_database_transaction(
                (
                    "load configured source "
                    "cache bundles"
                ),
                load_all,
            )
        )
    except Exception as error:
        print(
            "CONFIGURED SOURCE DB CACHE "
            "BULK LOAD ERROR | "
            f"Error: {error}"
        )

        bundles = {
            namespace: {
                "state": None,
                "jobs": [],
            }
            for namespace
            in namespaces
        }

    cache_map = {}
    refresh_targets = []
    cache_hits = 0

    for source_config in source_configs:
        namespace = (
            namespace_by_id[
                source_config.id
            ]
        )
        signature = (
            signature_by_id[
                source_config.id
            ]
        )
        bundle = (
            bundles.get(
                namespace
            )
            or {
                "state": None,
                "jobs": [],
            }
        )

        if cache_state_is_fresh(
            bundle.get(
                "state"
            ),
            profile_signature=signature,
            refresh_interval=(
                CONFIGURED_SOURCE_REFRESH_INTERVAL
            ),
        ):
            cache_hits += 1

            cache_map[
                source_config.id
            ] = {
                "namespace": namespace,
                "jobs": list(
                    bundle.get(
                        "jobs"
                    )
                    or []
                ),
                "mode": "database",
                "refresh_error": None,
            }
            continue

        refresh_targets.append(
            source_config
        )

        cache_map[
            source_config.id
        ] = {
            "namespace": namespace,
            "jobs": list(
                bundle.get(
                    "jobs"
                )
                or []
            ),
            "mode": (
                "stale"
                if bundle.get(
                    "jobs"
                )
                else "missing"
            ),
            "refresh_error": None,
        }

    print(
        "CONFIGURED SOURCE DB CACHE PLAN | "
        f"Boards: {len(source_configs)} | "
        f"Fresh hits: {cache_hits} | "
        f"Refresh needed: "
        f"{len(refresh_targets)} | "
        f"Workers: "
        f"{CONFIGURED_SOURCE_REFRESH_WORKERS}"
    )

    if not refresh_targets:
        return cache_map

    for (
        source_config,
        result,
        refresh_error,
    ) in iter_configured_source_refreshes(
        profiles,
        refresh_targets,
    ):
        namespace = (
            namespace_by_id[
                source_config.id
            ]
        )
        signature = (
            signature_by_id[
                source_config.id
            ]
        )
        existing_entry = (
            cache_map[
                source_config.id
            ]
        )

        if refresh_error is not None:
            error_text = str(
                refresh_error
            )

            existing_entry[
                "refresh_error"
            ] = error_text

            print(
                "CONFIGURED SOURCE REFRESH "
                "ERROR | "
                f"Company: "
                f"{source_config.company_name} | "
                f"Source: "
                f"{source_config.source_type} | "
                f"Error: {error_text}"
            )

            def persist_failure():
                record_source_cache_failure(
                    source_type=namespace,
                    source_name=(
                        (
                            f"{source_config.source_type}: "
                            f"{source_config.company_name}"
                        )[:120]
                    ),
                    error=error_text,
                )

            try:
                run_database_transaction(
                    (
                        "record configured source "
                        f"cache failure {namespace}"
                    ),
                    persist_failure,
                )
            except Exception as status_error:
                print(
                    "CONFIGURED SOURCE CACHE "
                    "FAILURE STATUS ERROR | "
                    f"Namespace: {namespace} | "
                    f"Error: {status_error}"
                )

            if existing_entry[
                "jobs"
            ]:
                existing_entry[
                    "mode"
                ] = "stale_fallback"

                print(
                    "CONFIGURED SOURCE STALE "
                    "FALLBACK | "
                    f"Company: "
                    f"{source_config.company_name} | "
                    f"Jobs: "
                    f"{len(existing_entry['jobs'])}"
                )
            else:
                existing_entry[
                    "mode"
                ] = "failed"

            continue

        jobs = list(
            result.get(
                "jobs"
            )
            or []
        )
        display_name = (
            result.get(
                "display_name"
            )
            or (
                f"{source_config.source_type}: "
                f"{source_config.company_name}"
            )
        )[:120]
        complete_inventory = bool(
            result.get(
                "complete_inventory"
            )
        )

        def persist_refresh():
            stats = (
                upsert_cached_source_jobs(
                    source_type=namespace,
                    source_name=display_name,
                    jobs=jobs,
                    profile_signature=signature,
                    cache_scope=(
                        "configured_board"
                    ),
                )
            )

            pruned = 0

            if complete_inventory:
                pruned = (
                    prune_missing_configured_jobs(
                        namespace,
                        jobs,
                    )
                )

            (
                cache_state,
                persisted_jobs,
            ) = load_source_cache_bundle(
                namespace
            )

            return (
                stats,
                pruned,
                persisted_jobs,
            )

        try:
            (
                stats,
                pruned,
                persisted_jobs,
            ) = run_database_transaction(
                (
                    "persist configured source "
                    f"cache {namespace}"
                ),
                persist_refresh,
            )

        except Exception as error:
            error_text = str(
                error
            )

            existing_entry[
                "refresh_error"
            ] = error_text

            print(
                "CONFIGURED SOURCE DB CACHE "
                "WRITE ERROR | "
                f"Company: "
                f"{source_config.company_name} | "
                f"Source: "
                f"{source_config.source_type} | "
                f"Error: {error_text}"
            )

            if existing_entry[
                "jobs"
            ]:
                existing_entry[
                    "mode"
                ] = "stale_fallback"
            else:
                existing_entry[
                    "mode"
                ] = "failed"

            continue

        cache_map[
            source_config.id
        ] = {
            "namespace": namespace,
            "jobs": list(
                persisted_jobs
            ),
            "mode": "refreshed",
            "refresh_error": None,
        }

        print(
            "CONFIGURED SOURCE DB CACHE WRITE | "
            f"Company: "
            f"{source_config.company_name} | "
            f"Source: "
            f"{source_config.source_type} | "
            f"Received: "
            f"{stats['received']} | "
            f"Created: "
            f"{stats['created']} | "
            f"Updated: "
            f"{stats['updated']} | "
            f"Active: "
            f"{stats['active']} | "
            f"Pruned closed/missing: "
            f"{pruned}"
        )

    refreshed = sum(
        1
        for entry in cache_map.values()
        if entry.get(
            "mode"
        ) == "refreshed"
    )
    stale_fallbacks = sum(
        1
        for entry in cache_map.values()
        if entry.get(
            "mode"
        ) == "stale_fallback"
    )
    failures = sum(
        1
        for entry in cache_map.values()
        if entry.get(
            "mode"
        ) == "failed"
    )

    print(
        "CONFIGURED SOURCE DB CACHE READY | "
        f"Fresh hits: {cache_hits} | "
        f"Refreshed: {refreshed} | "
        f"Stale fallbacks: "
        f"{stale_fallbacks} | "
        f"Failed without cache: "
        f"{failures}"
    )

    return cache_map


def run_configured_source(
    profile,
    source_config,
    configured_source_caches,
):
    source_type = (
        source_config.source_type
        or ""
    ).strip().lower()

    entry = (
        configured_source_caches.get(
            source_config.id
        )
    )

    if entry is None:
        raise RuntimeError(
            "Configured source cache entry "
            f"is missing for source "
            f"{source_config.id}."
        )

    cached_jobs = list(
        entry.get(
            "jobs"
        )
        or []
    )
    mode = (
        entry.get(
            "mode"
        )
        or "unknown"
    )
    refresh_error = entry.get(
        "refresh_error"
    )

    if (
        mode == "failed"
        and not cached_jobs
    ):
        raise RuntimeError(
            refresh_error
            or (
                "Configured source refresh "
                "failed without a usable cache."
            )
        )

    print(
        "JOB SOURCE: checking cached "
        f"{source_config.company_name} "
        f"through {source_type}."
    )

    with collect_match_diagnostics() as diagnostics:
        jobs = [
            job
            for job
            in cached_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

    if should_print_match_summary(
        diagnostics
    ):
        print(
            format_match_diagnostics(
                profile.name,
                (
                    f"{source_type}: "
                    f"{source_config.company_name}"
                ),
                diagnostics,
            )
        )

    print(
        "CONFIGURED SOURCE DB CACHE SEARCH | "
        f"Company: "
        f"{source_config.company_name} | "
        f"Source: {source_type} | "
        f"Mode: {mode} | "
        f"Cached: {len(cached_jobs)} | "
        f"Matched: {len(jobs)}"
    )

    return jobs



def run_global_source(
    profile,
    source_type,
    global_sources,
):
    source = global_sources[
        source_type
    ]

    print(
        "JOB SOURCE: checking global source "
        f"{source.source_name}."
    )

    cache_mode = getattr(
        source,
        "_db_cache_mode",
        None,
    )

    with collect_match_diagnostics() as diagnostics:
        if cache_mode == "database":
            cached_jobs = getattr(
                source,
                "_db_cached_jobs",
                [],
            )

            jobs = [
                job
                for job
                in cached_jobs
                if job_matches_profile(
                    job,
                    profile,
                )
            ]

        else:
            jobs = source.search(
                profile=profile,
                source_config=None,
            )

            if cache_mode == "network":
                accumulator = getattr(
                    source,
                    "_db_cache_accumulator",
                    None,
                )

                if isinstance(
                    accumulator,
                    dict,
                ):
                    for job in jobs:
                        if not isinstance(
                            job,
                            dict,
                        ):
                            continue

                        cache_key = str(
                            job.get(
                                "external_id"
                            )
                            or job.get(
                                "posting_url"
                            )
                            or ""
                        ).strip()

                        if not cache_key:
                            continue

                        accumulator[
                            cache_key
                        ] = job

    if cache_mode == "database":
        print(
            "GLOBAL SOURCE DB CACHE SEARCH | "
            f"Source: "
            f"{source.source_name} | "
            f"Profile: {profile.name} | "
            f"Cached: "
            f"{len(getattr(source, '_db_cached_jobs', []))} | "
            f"Matched: {len(jobs)}"
        )

    if should_print_match_summary(
        diagnostics
    ):
        print(
            format_match_diagnostics(
                profile.name,
                source.source_name,
                diagnostics,
            )
        )

    return source, jobs

def process_search_profile(
    profile,
    source_configs,
    global_sources,
    configured_source_caches,
):
    all_matching_jobs = []
    source_errors = []
    source_status_updates = []

    keywords = parse_profile_values(
        profile.keywords
    )
    locations = parse_profile_values(
        profile.locations
    )
    employment_types = (
        parse_profile_values(
            profile.employment_types
        )
    )

    if any(
        employment_type.lower()
        in {"all", "any"}
        for employment_type
        in employment_types
    ):
        employment_types = []

    print(
        f"SEARCH PROFILE: {profile.name} | "
        f"Keywords: {keywords} | "
        f"Locations: {locations} | "
        "Employment Types: "
        f"{employment_types or ['All']}"
    )

    # Run company-configured ATS sources such as:
    # Greenhouse, Lever, and Ashby.
    for source_config in source_configs:
        checked_at = datetime.now(
            timezone.utc
        )

        try:
            source_jobs = (
                run_configured_source(
                    profile,
                    source_config,
                    configured_source_caches,
                )
            )
            all_matching_jobs.extend(
                source_jobs
            )
            source_status_updates.append({
                "id": source_config.id,
                "last_checked_at": checked_at,
                "last_check_status": (
                    "Completed"
                ),
                "last_check_error": None,
            })

            print(
                f"{source_config.source_type.upper()} "
                f"RESULTS FOR {profile.name}: "
                f"{len(source_jobs)} matched."
            )

        except Exception as error:
            source_status_updates.append({
                "id": source_config.id,
                "last_checked_at": checked_at,
                "last_check_status": "Failed",
                "last_check_error": str(error),
            })

            error_message = (
                f"{source_config.company_name} "
                f"({source_config.source_type}): "
                f"{error}"
            )
            source_errors.append(
                error_message
            )

            print(
                "JOB SOURCE ERROR:",
                error_message,
            )

    # Run global feeds such as Remote OK.
    # These do not require JobSourceCompany records.
    for source_type in GLOBAL_SOURCE_TYPES:
        try:
            (
                source,
                source_jobs,
            ) = run_global_source(
                profile,
                source_type,
                global_sources,
            )

            all_matching_jobs.extend(
                source_jobs
            )

            print(
                f"{source.source_name.upper()} "
                f"RESULTS FOR {profile.name}: "
                f"{len(source_jobs)} matched."
            )

        except Exception as error:
            cache_source = (
                global_sources.get(
                    source_type
                )
            )

            if cache_source is not None:
                cache_errors = getattr(
                    cache_source,
                    "_db_cache_errors",
                    None,
                )

                if isinstance(
                    cache_errors,
                    list,
                ):
                    cache_errors.append(
                        str(error)
                    )

            error_message = (
                f"Global source "
                f"{source_type}: {error}"
            )
            source_errors.append(
                error_message
            )

            print(
                "GLOBAL JOB SOURCE ERROR:",
                error_message,
            )

    return (
        len(all_matching_jobs),
        all_matching_jobs,
        source_errors,
        source_status_updates,
    )


def process_active_search_profiles(app):
    with app.app_context():
        try:
            (
                profiles,
                source_configs,
            ) = load_scheduler_snapshots()

        except Exception as error:
            print(
                "JOB SEARCH SCHEDULER "
                "DATABASE ERROR:",
                repr(error),
            )
            return

        profile_ids = [
            profile.id
            for profile in profiles
        ]
        global_sources = (
            create_global_sources()
        )

        configured_source_count = len(
            source_configs
        )
        global_source_count = len(
            GLOBAL_SOURCE_TYPES
        )
        total_source_count = (
            configured_source_count
            + global_source_count
        )

        print(
            "JOB SEARCH SCHEDULER: "
            f"found {len(profile_ids)} "
            "active profiles, "
            f"{configured_source_count} "
            "configured sources, "
            f"{global_source_count} "
            "global sources, "
            f"and {total_source_count} "
            "total sources."
        )

        # At this point profiles and source configs are
        # plain snapshots. No PostgreSQL connection is
        # held during the network-heavy preparation or
        # source crawling below.
        prepare_global_sources(
            profiles,
            global_sources,
        )

        configured_source_caches = (
            prepare_configured_source_caches(
                profiles,
                source_configs,
            )
        )

        for profile in profiles:
            if not profile.active:
                continue

            try:
                (
                    matched_count,
                    matching_jobs,
                    source_errors,
                    source_status_updates,
                ) = process_search_profile(
                    profile,
                    source_configs,
                    global_sources,
                    configured_source_caches,
                )

                result = persist_profile_results(
                    profile.id,
                    matching_jobs,
                    matched_count,
                    source_errors,
                    source_status_updates,
                )

                if result["skipped"]:
                    print(
                        "SEARCH PROFILE SKIPPED | "
                        f"Profile ID: {profile.id} | "
                        "Profile was removed or disabled "
                        "during the crawl."
                    )
                    continue

                print(
                    f"SEARCH COMPLETE: "
                    f"{result['profile_name']} | "
                    f"{matched_count} matched | "
                    f"{result['saved_count']} "
                    "newly saved."
                )

            except Exception as error:
                try:
                    failure_profile_name = (
                        persist_profile_failure(
                            profile.id,
                            error,
                        )
                    )
                except Exception as status_error:
                    failure_profile_name = (
                        profile.name
                    )
                    print(
                        "SEARCH PROFILE FAILURE "
                        "STATUS ERROR | "
                        f"Profile ID: "
                        f"{profile.id} | "
                        f"Error: {status_error}"
                    )

                print(
                    "SEARCH PROFILE ERROR: "
                    f"{profile.id} "
                    f"({failure_profile_name or profile.name}):",
                    repr(error),
                )

        finalize_global_source_db_cache(
            global_sources
        )


def serialize_datetime(value):
    if value is None:
        return None

    return value.isoformat()


def set_automatic_discovery_status(**updates):
    with _automatic_discovery_lock:
        _automatic_discovery_status.update(updates)


def get_automatic_source_discovery_status():
    with _automatic_discovery_lock:
        status = dict(_automatic_discovery_status)

    status["started_at"] = serialize_datetime(
        status.get("started_at")
    )
    status["completed_at"] = serialize_datetime(
        status.get("completed_at")
    )
    return status


def format_automatic_discovery_message(results):
    source_counts = results.get("by_source", {})
    source_failures = results.get("source_failures", {})
    failed_source_text = ""

    if source_failures:
        failed_source_text = (
            " Sources temporarily unavailable: "
            + ", ".join(
                source_type.title()
                for source_type in source_failures
            )
            + "."
        )

    return (
        "Automatic discovery complete. "
        f"{results.get('found', 0)} plausible boards found: "
        f"{source_counts.get('lever', 0)} Lever, "
        f"{source_counts.get('greenhouse', 0)} Greenhouse, "
        f"{source_counts.get('ashby', 0)} Ashby. "
        f"{results.get('created', 0)} valid candidates added, "
        f"{results.get('invalid_rejected', 0)} invalid boards discarded, "
        f"{results.get('already_active', 0)} already active, "
        f"{results.get('already_blocked', 0)} previously rejected, "
        f"{results.get('already_candidate', 0)} already awaiting review, "
        f"{results.get('failed', 0)} failed."
        f"{failed_source_text}"
    )


def process_automatic_source_discovery(
    app,
    run_id,
    limit_per_source=20,
):
    set_automatic_discovery_status(
        run_id=run_id,
        state="running",
        message="Automatic discovery is running.",
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error=None,
        results=None,
    )

    print(
        "AUTOMATIC DISCOVERY BACKGROUND START | "
        f"Run ID: {run_id}"
    )

    with app.app_context():
        try:
            results = run_common_crawl_discovery(
                limit_per_source=limit_per_source
            )
            message = format_automatic_discovery_message(results)

            set_automatic_discovery_status(
                run_id=run_id,
                state="completed",
                message=message,
                completed_at=datetime.now(timezone.utc),
                error=None,
                results=results,
            )

            print(
                "AUTOMATIC DISCOVERY BACKGROUND COMPLETE | "
                f"Run ID: {run_id} | "
                f"Created: {results.get('created', 0)}"
            )

        except Exception as error:
            try:
                db.session.rollback()
            except Exception:
                pass

            error_message = str(error)
            set_automatic_discovery_status(
                run_id=run_id,
                state="failed",
                message=(
                    "Automatic discovery failed: "
                    f"{error_message}"
                ),
                completed_at=datetime.now(timezone.utc),
                error=error_message,
                results=None,
            )

            print(
                "AUTOMATIC DISCOVERY BACKGROUND FAILED | "
                f"Run ID: {run_id} | Error: {error}"
            )

        finally:
            db.session.remove()


def queue_automatic_source_discovery(
    app,
    limit_per_source=20,
):
    with _automatic_discovery_lock:
        current_state = _automatic_discovery_status["state"]

        if current_state in {"queued", "running"}:
            return False, dict(_automatic_discovery_status)

        run_id = uuid.uuid4().hex
        _automatic_discovery_status.update({
            "run_id": run_id,
            "state": "queued",
            "message": "Automatic discovery was queued.",
            "started_at": None,
            "completed_at": None,
            "error": None,
            "results": None,
        })

    try:
        scheduler.add_job(
            process_automatic_source_discovery,
            "date",
            run_date=datetime.now(timezone.utc),
            args=[app, run_id, limit_per_source],
            id=AUTOMATIC_DISCOVERY_JOB_ID,
            replace_existing=False,
            max_instances=1,
            misfire_grace_time=300,
        )

    except Exception as error:
        error_message = str(error)
        set_automatic_discovery_status(
            run_id=run_id,
            state="failed",
            message=(
                "Automatic discovery could not be queued: "
                f"{error_message}"
            ),
            completed_at=datetime.now(timezone.utc),
            error=error_message,
        )
        raise

    return True, get_automatic_source_discovery_status()


def start_scheduler(app):
    if scheduler.running:
        return

    scheduler.add_job(
        process_active_search_profiles,
        "interval",
        hours=6,
        args=[app],
        id="process_active_search_profiles",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(
            timezone.utc
        ),
    )

    scheduler.start()
