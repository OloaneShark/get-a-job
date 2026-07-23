
import re
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from models import (
    DiscoveredJob,
    JobSearchProfile,
    JobSourceCompany,
    db
)
from services.job_sources.registry import create_source
from services.job_sources.utils import build_job_fingerprint


scheduler = BackgroundScheduler(timezone="UTC")


def parse_profile_values(value):
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[\n,]+", value)
        if item.strip()
    ]


def save_discovered_jobs(profile, jobs):
    saved_count = 0

    for job in jobs:
        posting_url = job.get("posting_url")

        if not posting_url:
            continue

        fingerprint = build_job_fingerprint(
            job.get("company_name"),
            job.get("position_title"),
            job.get("location"),
            posting_url
        )

        existing_job = DiscoveredJob.query.filter_by(
            user_id=profile.user_id,
            fingerprint=fingerprint
        ).first()

        if existing_job:
            continue

        discovered_job = DiscoveredJob(
            user_id=profile.user_id,
            search_profile_id=profile.id,
            source=job.get("source") or "Unknown",
            external_id=job.get("external_id"),
            company_name=(
                job.get("company_name")
                or "Unknown Company"
            ),
            position_title=(
                job.get("position_title")
                or "Untitled Position"
            ),
            location=job.get("location"),
            employment_type=job.get("employment_type"),
            salary=job.get("salary"),
            visa_sponsorship=(
                job.get("visa_sponsorship")
                or "Unknown"
            ),
            posting_url=posting_url,
            apply_url=job.get("apply_url") or posting_url,
            job_description=job.get("job_description"),
            recruiter_name=job.get("recruiter_name"),
            recruiter_email=job.get("recruiter_email"),
            recruiter_contact_url=job.get(
                "recruiter_contact_url"
            ),
            recruiter_contact_source=job.get(
                "recruiter_contact_source"
            ),
            fingerprint=fingerprint
        )

        db.session.add(discovered_job)
        saved_count += 1

    return saved_count


def get_active_source_configs():
    return (
        JobSourceCompany.query
        .filter_by(is_active=True)
        .order_by(
            JobSourceCompany.source_type.asc(),
            JobSourceCompany.company_name.asc()
        )
        .all()
    )


def run_configured_source(
    profile,
    source_config
):
    source_type = (
        source_config.source_type
        or ""
    ).strip().lower()

    source = create_source(source_type)

    print(
        f"JOB SOURCE: checking "
        f"{source_config.company_name} "
        f"through {source.source_name}."
    )

    jobs = source.search(
        profile=profile,
        source_config=source_config
    )

    source_config.last_checked_at = datetime.now(
        timezone.utc
    )
    source_config.last_check_status = "Completed"
    source_config.last_check_error = None

    return jobs


def process_search_profile(
    profile,
    source_configs
):
    all_matching_jobs = []
    source_errors = []

    keywords = parse_profile_values(profile.keywords)
    locations = parse_profile_values(profile.locations)
    employment_types = parse_profile_values(
        profile.employment_types
    )

    if any(
        employment_type.lower() in {"all", "any"}
        for employment_type in employment_types
    ):
        employment_types = []

    print(
        f"SEARCH PROFILE: {profile.name} | "
        f"Keywords: {keywords} | "
        f"Locations: {locations} | "
        f"Employment Types: "
        f"{employment_types or ['All']}"
    )

    for source_config in source_configs:
        try:
            source_jobs = run_configured_source(
                profile,
                source_config
            )

            all_matching_jobs.extend(source_jobs)

            print(
                f"{source_config.source_type.upper()} "
                f"RESULTS FOR {profile.name}: "
                f"{len(source_jobs)} matched."
            )

        except Exception as error:
            source_config.last_checked_at = datetime.now(
                timezone.utc
            )
            source_config.last_check_status = "Failed"
            source_config.last_check_error = str(error)

            error_message = (
                f"{source_config.company_name} "
                f"({source_config.source_type}): "
                f"{error}"
            )

            source_errors.append(error_message)

            print(
                "JOB SOURCE ERROR:",
                error_message
            )

    saved_count = save_discovered_jobs(
        profile,
        all_matching_jobs
    )

    return (
        len(all_matching_jobs),
        saved_count,
        source_errors
    )


def process_active_search_profiles(app):
    with app.app_context():
        profile_ids = [
            profile.id
            for profile in JobSearchProfile.query.filter_by(
                active=True
            ).all()
        ]

        source_configs = get_active_source_configs()

        print(
            f"JOB SEARCH SCHEDULER: "
            f"found {len(profile_ids)} active profiles "
            f"and {len(source_configs)} active sources."
        )

        for profile_id in profile_ids:
            profile = db.session.get(
                JobSearchProfile,
                profile_id
            )

            if not profile or not profile.active:
                continue

            try:
                (
                    matched_count,
                    saved_count,
                    source_errors
                ) = process_search_profile(
                    profile,
                    source_configs
                )

                profile.last_searched_at = datetime.now(
                    timezone.utc
                )
                profile.last_result_count = saved_count

                if source_errors:
                    profile.last_search_status = (
                        "Completed With Errors"
                    )
                    profile.last_search_error = "\n".join(
                        source_errors
                    )
                else:
                    profile.last_search_status = "Completed"
                    profile.last_search_error = None

                db.session.commit()

                print(
                    f"SEARCH COMPLETE: {profile.name} | "
                    f"{matched_count} matched | "
                    f"{saved_count} newly saved."
                )

            except Exception as error:
                db.session.rollback()

                profile = db.session.get(
                    JobSearchProfile,
                    profile_id
                )

                if profile:
                    profile.last_searched_at = datetime.now(
                        timezone.utc
                    )
                    profile.last_result_count = 0
                    profile.last_search_status = "Failed"
                    profile.last_search_error = str(error)

                    db.session.commit()

                print(
                    f"SEARCH PROFILE ERROR: "
                    f"{profile_id}:",
                    repr(error)
                )


def start_scheduler(app):
    if scheduler.running:
        return

    scheduler.add_job(
        process_active_search_profiles,
        "interval",
        minutes=1,
        args=[app],
        id="process_active_search_profiles",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    scheduler.start()
    
