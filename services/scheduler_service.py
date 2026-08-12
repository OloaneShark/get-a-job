
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
)
from services.job_sources.utils import (
    build_job_fingerprint,
    cross_source_jobs_match,
    source_dedupe_family,
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

        canonical_posting_url = (
            str(posting_url)
            .strip()
            .rstrip("/")
        )
        posting_url_variants = {
            canonical_posting_url,
            f"{canonical_posting_url}/",
        }

        existing_job = None

        if external_id:
            existing_job = (
                DiscoveredJob.query
                .filter(
                    DiscoveredJob.user_id
                    == profile.user_id,
                    DiscoveredJob.source
                    == source,
                    DiscoveredJob.external_id
                    == external_id,
                )
                .first()
            )

        if existing_job is None:
            family = source_dedupe_family(
                source
            )

            if family is not None:
                candidate_jobs = (
                    DiscoveredJob.query
                    .filter(
                        DiscoveredJob.user_id
                        == profile.user_id
                    )
                    .all()
                )

                for candidate in candidate_jobs:
                    if cross_source_jobs_match(
                        candidate,
                        job,
                    ):
                        existing_job = candidate
                        break

        if existing_job is None:
            existing_job = (
                DiscoveredJob.query
                .filter(
                    DiscoveredJob.user_id
                    == profile.user_id,
                    db.or_(
                        DiscoveredJob.fingerprint
                        == fingerprint,
                        DiscoveredJob.posting_url.in_(
                            posting_url_variants
                        ),
                    ),
                )
                .first()
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


def prepare_global_sources(
    profiles,
    global_sources,
):
    for source_type in GLOBAL_SOURCE_TYPES:
        source = global_sources[
            source_type
        ]
        prepare = getattr(
            source,
            "prepare",
            None,
        )

        if not callable(prepare):
            continue

        try:
            print(
                "GLOBAL SOURCE PREPARE | "
                f"Preparing shared "
                f"{source.source_name} feed "
                f"for {len(profiles)} "
                "active profiles."
            )
            prepare(profiles)

        except Exception as error:
            # Keep the scheduler alive. The source's search()
            # method may retry for an individual profile, and
            # the failure will still be recorded normally.
            print(
                "GLOBAL SOURCE PREPARE ERROR | "
                f"{source.source_name}: "
                f"{error}"
            )


def run_configured_source(
    profile,
    source_config,
):
    source_type = (
        source_config.source_type
        or ""
    ).strip().lower()

    source = create_source(
        source_type
    )

    print(
        "JOB SOURCE: checking "
        f"{source_config.company_name} "
        f"through {source.source_name}."
    )

    with collect_match_diagnostics() as diagnostics:
        jobs = source.search(
            profile=profile,
            source_config=source_config,
        )

    if should_print_match_summary(
        diagnostics
    ):
        print(
            format_match_diagnostics(
                profile.name,
                (
                    f"{source.source_name}: "
                    f"{source_config.company_name}"
                ),
                diagnostics,
            )
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

    with collect_match_diagnostics() as diagnostics:
        jobs = source.search(
            profile=profile,
            source_config=None,
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
        hours=1,
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
