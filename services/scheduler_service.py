
from datetime import datetime, timezone
import re

from apscheduler.schedulers.background import BackgroundScheduler

from models import JobSearchProfile, db


scheduler = BackgroundScheduler(timezone="UTC")


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
        profiles = JobSearchProfile.query.filter_by(
            active=True
        ).all()

        print(
            f"JOB SEARCH SCHEDULER: "
            f"found {len(profiles)} active profiles."
        )

        for profile in profiles:
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

                profile.last_searched_at = datetime.now(
                    timezone.utc
                )

                profile.last_result_count = 0
                profile.last_search_status = "Test Completed"
                profile.last_search_error = None

            except Exception as e:
                profile.last_searched_at = datetime.now(
                    timezone.utc
                )

                profile.last_search_status = "Failed"
                profile.last_search_error = str(e)

                print(
                    f"SEARCH PROFILE ERROR: "
                    f"{profile.name}:",
                    repr(e)
                )

        db.session.commit()


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
    