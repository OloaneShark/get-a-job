
import re
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from models import DiscoveredJob, JobSearchProfile, db
from services.job_sources.company_registry import GREENHOUSE_COMPANIES
from services.job_sources.greenhouse import GreenhouseJobSource
from services.job_sources.utils import build_job_fingerprint


scheduler = BackgroundScheduler(timezone="UTC")
greenhouse_source = GreenhouseJobSource()


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
            fingerprint=fingerprint
        )

        db.session.add(discovered_job)
        saved_count += 1

    return saved_count


def search_greenhouse_for_profile(profile):
    matched_jobs = []
    source_errors = []

    for company in GREENHOUSE_COMPANIES:
        company_name = company.get("company_name")
        board_token = company.get("board_token")

        try:
            company_jobs = greenhouse_source.search(
                profile=profile,
                board_token=board_token,
                company_name=company_name
            )

            matched_jobs.extend(company_jobs)

        except Exception as error:
            error_message = (
                f"{company_name}: {error}"
            )

            source_errors.append(error_message)

            print(
                f"GREENHOUSE SOURCE ERROR: "
                f"{company_name}:",
                repr(error)
            )

    return matched_jobs, source_errors


def process_active_search_profiles(app):
    with app.app_context():
        profile_ids = [
            profile.id
            for profile in JobSearchProfile.query.filter_by(
                active=True
            ).all()
        ]

        print(
            f"JOB SEARCH SCHEDULER: "
            f"found {len(profile_ids)} active profiles."
        )

        for profile_id in profile_ids:
            profile = db.session.get(
                JobSearchProfile,
                profile_id
            )

            if not profile or not profile.active:
                continue

            try:
                keywords = parse_profile_values(
                    profile.keywords
                )

                locations = parse_profile_values(
                    profile.locations
                )

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

                greenhouse_jobs, source_errors = (
                    search_greenhouse_for_profile(profile)
                )

                saved_count = save_discovered_jobs(
                    profile,
                    greenhouse_jobs
                )

                print(
                    f"GREENHOUSE RESULTS FOR "
                    f"{profile.name}: "
                    f"{len(greenhouse_jobs)} matched, "
                    f"{saved_count} newly saved."
                )

                for job in greenhouse_jobs[:10]:
                    print(
                        f"- {job['company_name']} | "
                        f"{job['position_title']} | "
                        f"{job['location']} | "
                        f"{job['posting_url']}"
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
    