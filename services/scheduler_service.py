
import re
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from models import JobSearchProfile, db
from services.job_sources.company_registry import GREENHOUSE_COMPANIES
from services.job_sources.greenhouse import GreenhouseJobSource


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


def process_active_search_profiles(app):
    with app.app_context():
        profiles = JobSearchProfile.query.filter_by(active=True).all()

        print(
            f"JOB SEARCH SCHEDULER: "
            f"found {len(profiles)} active profiles."
        )

        for profile in profiles:
            try:
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

                greenhouse_jobs = []

                for company in GREENHOUSE_COMPANIES:
                    try:
                        company_jobs = greenhouse_source.search(
                            profile=profile,
                            board_token=company["board_token"],
                            company_name=company["company_name"]
                        )

                        greenhouse_jobs.extend(company_jobs)

                    except Exception as source_error:
                        print(
                            f"GREENHOUSE SOURCE ERROR: "
                            f"{company['company_name']}:",
                            repr(source_error)
                        )

                print(
                    f"GREENHOUSE MATCHES FOR "
                    f"{profile.name}: "
                    f"{len(greenhouse_jobs)}"
                )

                for job in greenhouse_jobs[:10]:
                    print(
                        f"- {job['company_name']} | "
                        f"{job['position_title']} | "
                        f"{job['location']} | "
                        f"{job['posting_url']}"
                    )

                profile.last_searched_at = datetime.now(timezone.utc)
                profile.last_result_count = len(greenhouse_jobs)
                profile.last_search_status = "Completed"
                profile.last_search_error = None

            except Exception as e:
                db.session.rollback()

                profile.last_searched_at = datetime.now(timezone.utc)
                profile.last_result_count = 0
                profile.last_search_status = "Failed"
                profile.last_search_error = str(e)

                print(
                    f"SEARCH PROFILE ERROR: "
                    f"{profile.name}:",
                    repr(e)
                )

        try:
            db.session.commit()

        except Exception as e:
            db.session.rollback()

            print(
                "JOB SEARCH SCHEDULER DATABASE ERROR:",
                repr(e)
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
    