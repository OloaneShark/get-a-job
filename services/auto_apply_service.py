import json
import re
from datetime import datetime

from models import (
    AutoApplyCandidate,
    DiscoveredJob,
    JobApplication,
    Resume,
    User,
    db,
)
from services.job_sources.utils import (
    normalize_identity_text,
)


PREMIUM_AUTO_APPLY_DAILY_MAX = 50
AUTO_APPLY_PAID_PLANS = {
    "premium",
}


def get_auto_apply_access(user):
    if user is None:
        return {
            "allowed": False,
            "unlimited": False,
            "daily_max": 0,
            "tier": "none",
        }

    if bool(getattr(user, "is_admin", False)):
        return {
            "allowed": True,
            "unlimited": True,
            "daily_max": None,
            "tier": "admin",
        }

    plan = str(
        getattr(user, "plan", "free")
        or "free"
    ).strip().lower()

    if plan in AUTO_APPLY_PAID_PLANS:
        return {
            "allowed": True,
            "unlimited": False,
            "daily_max": PREMIUM_AUTO_APPLY_DAILY_MAX,
            "tier": plan,
        }

    return {
        "allowed": False,
        "unlimited": False,
        "daily_max": 0,
        "tier": plan,
    }


def _canonical_url(value):
    return str(value or "").strip().rstrip("/")


def _split(value):
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[\n,]+", str(value))
        if item.strip()
    ]


def _snapshot(profile, access):
    return json.dumps(
        {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "resume_id": profile.auto_apply_resume_id,
            "cover_letter_mode": profile.auto_apply_cover_letter_mode,
            "application_email": profile.auto_apply_contact_email,
            "profile_daily_limit": profile.auto_apply_daily_limit,
            "account_daily_max": access["daily_max"],
            "account_unlimited": access["unlimited"],
            "excluded_companies": _split(
                profile.auto_apply_excluded_companies
            ),
            "locations": _split(profile.locations),
            "employment_types": _split(profile.employment_types),
            "workplace_types": _split(profile.workplace_types),
            "experience_levels": _split(profile.experience_levels),
            "minimum_salary": profile.minimum_salary,
            "visa_preference": profile.visa_preference,
            "overseas_applicant_preference": (
                profile.overseas_applicant_preference
            ),
        },
        sort_keys=True,
    )


def stage_auto_apply_candidates(profile, jobs):
    stats = {
        "enabled": bool(
            getattr(profile, "auto_apply_enabled", False)
        ),
        "entitled": False,
        "access_denied": 0,
        "considered": 0,
        "staged": 0,
        "already_queued": 0,
        "already_applied": 0,
        "ignored": 0,
        "excluded_company": 0,
        "daily_limit": 0,
        "invalid_resume": 0,
    }

    if not stats["enabled"]:
        return stats

    user = db.session.get(
        User,
        profile.user_id,
    )

    access = get_auto_apply_access(user)
    stats["entitled"] = bool(access["allowed"])

    if not access["allowed"]:
        stats["access_denied"] = 1
        return stats

    resume_id = getattr(
        profile,
        "auto_apply_resume_id",
        None,
    )

    if not resume_id:
        stats["invalid_resume"] = 1
        return stats

    resume = db.session.get(
        Resume,
        resume_id,
    )

    if (
        resume is None
        or resume.user_id != profile.user_id
    ):
        stats["invalid_resume"] = 1
        return stats

    unique_jobs = []
    seen = set()

    for job in jobs:
        if (
            job is None
            or id(job) in seen
        ):
            continue

        seen.add(id(job))
        unique_jobs.append(job)

    if not unique_jobs:
        return stats

    # One flush for the whole profile batch, not one query/flush per job.
    db.session.flush()

    jobs_by_id = {
        job.id: job
        for job in unique_jobs
        if job.id is not None
    }

    stats["considered"] = len(jobs_by_id)

    if not jobs_by_id:
        return stats

    existing_ids = {
        row[0]
        for row in (
            db.session.query(
                AutoApplyCandidate.discovered_job_id
            )
            .filter(
                AutoApplyCandidate.user_id == profile.user_id,
                AutoApplyCandidate.discovered_job_id.in_(
                    list(jobs_by_id)
                ),
            )
            .all()
        )
    }

    stats["already_queued"] = len(existing_ids)

    excluded = {
        normalize_identity_text(name)
        for name in _split(
            getattr(
                profile,
                "auto_apply_excluded_companies",
                None,
            )
        )
        if normalize_identity_text(name)
    }

    urls = {
        _canonical_url(job.posting_url)
        for job in jobs_by_id.values()
        if _canonical_url(job.posting_url)
    }

    variants = set()

    for url in urls:
        variants.add(url)
        variants.add(f"{url}/")

    applied_urls = set()

    if variants:
        rows = (
            db.session.query(
                JobApplication.job_posting_url
            )
            .filter(
                JobApplication.user_id == profile.user_id,
                JobApplication.job_posting_url.in_(variants),
            )
            .all()
        )

        applied_urls = {
            _canonical_url(row[0])
            for row in rows
            if _canonical_url(row[0])
        }

    day_start = datetime.utcnow().replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    # Premium's 50/day maximum is ACCOUNT-WIDE across every profile.
    account_staged_today = (
        AutoApplyCandidate.query
        .filter(
            AutoApplyCandidate.user_id == profile.user_id,
            AutoApplyCandidate.created_at >= day_start,
        )
        .count()
    )

    profile_staged_today = (
        AutoApplyCandidate.query
        .filter(
            AutoApplyCandidate.user_id == profile.user_id,
            AutoApplyCandidate.search_profile_id == profile.id,
            AutoApplyCandidate.created_at >= day_start,
        )
        .count()
    )

    if access["unlimited"]:
        remaining = None
    else:
        account_remaining = max(
            0,
            int(
                access["daily_max"]
                or PREMIUM_AUTO_APPLY_DAILY_MAX
            )
            - account_staged_today,
        )

        try:
            configured_profile_limit = int(
                getattr(
                    profile,
                    "auto_apply_daily_limit",
                    PREMIUM_AUTO_APPLY_DAILY_MAX,
                )
                or PREMIUM_AUTO_APPLY_DAILY_MAX
            )
        except (TypeError, ValueError):
            configured_profile_limit = (
                PREMIUM_AUTO_APPLY_DAILY_MAX
            )

        configured_profile_limit = max(
            1,
            min(
                configured_profile_limit,
                PREMIUM_AUTO_APPLY_DAILY_MAX,
            ),
        )

        profile_remaining = max(
            0,
            configured_profile_limit
            - profile_staged_today,
        )

        remaining = min(
            account_remaining,
            profile_remaining,
        )

    application_email = (
        str(
            getattr(
                profile,
                "auto_apply_contact_email",
                None,
            )
            or user.email
            or ""
        )
        .strip()
        .lower()
    )

    if not application_email:
        stats["access_denied"] += 1
        return stats

    snapshot = _snapshot(
        profile,
        access,
    )

    for job_id, job in jobs_by_id.items():
        if job_id in existing_ids:
            continue

        if getattr(job, "is_ignored", False):
            stats["ignored"] += 1
            continue

        company = normalize_identity_text(
            getattr(job, "company_name", None)
        )

        if company and company in excluded:
            stats["excluded_company"] += 1
            continue

        url = _canonical_url(
            getattr(job, "posting_url", None)
        )

        if url and url in applied_urls:
            stats["already_applied"] += 1
            continue

        if (
            remaining is not None
            and remaining <= 0
        ):
            stats["daily_limit"] += 1
            continue

        db.session.add(
            AutoApplyCandidate(
                user_id=profile.user_id,
                search_profile_id=profile.id,
                discovered_job_id=job.id,
                resume_id=resume.id,
                status="Pending Review",
                cover_letter_mode=(
                    getattr(
                        profile,
                        "auto_apply_cover_letter_mode",
                        "when_required",
                    )
                    or "when_required"
                ),
                application_email=application_email,
                rule_snapshot_json=snapshot,
            )
        )

        existing_ids.add(job.id)
        stats["staged"] += 1

        if remaining is not None:
            remaining -= 1

    return stats

def stage_existing_auto_apply_matches(profile):
    # Database-only backfill for jobs already matched to this profile.
    jobs_by_id = {}

    for job in list(
        getattr(
            profile,
            "matched_jobs",
            [],
        )
        or []
    ):
        if job is not None and job.id is not None:
            jobs_by_id[job.id] = job

    direct_jobs = (
        DiscoveredJob.query
        .filter_by(
            user_id=profile.user_id,
            search_profile_id=profile.id,
        )
        .all()
    )

    for job in direct_jobs:
        if job.id is not None:
            jobs_by_id[job.id] = job

    return stage_auto_apply_candidates(
        profile,
        list(jobs_by_id.values()),
    )

