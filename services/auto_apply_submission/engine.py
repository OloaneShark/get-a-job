
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import current_app

from models import (
    ApplicantProfile,
    ApplicationHistory,
    ApplicationPackage,
    ApplicationSubmissionAttempt,
    JobApplication,
    db,
)
from services.auto_apply_service import get_auto_apply_access
from services.auto_apply_submission.adapters.lever_hosted import LeverHostedAdapter


from services.auto_apply_submission.application_question_service import (
    application_answers,
    dump_question_state,
    merge_questions,
)


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def canonical_url(value):
    return str(value or "").strip().rstrip("/")


def detect_adapter(job):
    target = canonical_url(job.apply_url or job.posting_url)
    host = (urlparse(target).hostname or "").lower()
    if host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return LeverHostedAdapter()
    return None


def resume_path(resume):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], resume.filename)


def get_or_create_application(candidate):
    if candidate.application_id:
        application = db.session.get(JobApplication, candidate.application_id)
        if application is not None:
            return application

    job = candidate.discovered_job
    canonical = canonical_url(job.posting_url)
    application = None

    if canonical:
        application = (
            JobApplication.query
            .filter_by(user_id=candidate.user_id)
            .filter(JobApplication.job_posting_url.in_([canonical, canonical + "/"]))
            .first()
        )

    if application is None:
        application = JobApplication(
            user_id=candidate.user_id,
            company_name=job.company_name,
            position_title=job.position_title,
            job_posting_url=job.posting_url,
            job_description=job.job_description,
            recruiter_email=job.recruiter_email,
            salary=job.salary,
            location=job.location,
            visa_sponsorship=job.visa_sponsorship or "Unknown",
            status="Auto Apply - Preparing",
            application_date=utcnow_naive(),
        )
        db.session.add(application)
        db.session.flush()

    candidate.application_id = application.id
    return application


def get_or_create_package(candidate, application):
    if candidate.application_package_id:
        package = db.session.get(ApplicationPackage, candidate.application_package_id)
        if package is not None:
            return package

    job = candidate.discovered_job
    snapshot = json.dumps({
        "discovered_job_id": job.id,
        "source": job.source,
        "external_id": job.external_id,
        "company_name": job.company_name,
        "position_title": job.position_title,
        "location": job.location,
        "posting_url": job.posting_url,
        "apply_url": job.apply_url,
    }, sort_keys=True)

    package = ApplicationPackage(
        user_id=candidate.user_id,
        application_id=application.id,
        resume_id=candidate.resume_id,
        status="Prepared",
        application_email=(candidate.application_email or candidate.search_profile.auto_apply_contact_email),
        discovered_job_id=candidate.discovered_job_id,
        job_snapshot_json=snapshot,
        cover_letter_text=None,
        answers_json=json.dumps({}),
    )
    db.session.add(package)
    db.session.flush()
    candidate.application_package_id = package.id
    return package


def execute_candidate_submission(
    candidate,
    user,
    resume_mode=False,
):
    access = get_auto_apply_access(user)
    now = utcnow_naive()

    if not access["allowed"]:
        return {"status": "Failed", "message": "Auto Apply is not enabled for this account tier.", "category": "danger"}

    identity = ApplicantProfile.query.filter_by(user_id=user.id).first()
    candidate.status = "Approved"
    candidate.reviewed_at = now

    if identity is None:
        candidate.execution_status = "Needs User Action"
        return {
            "status": "Needs User Action",
            "message": "Save your Applicant Profile before Jobfinitum submits applications.",
            "category": "warning",
        }

    application = get_or_create_application(candidate)
    package = get_or_create_package(candidate, application)
    adapter = detect_adapter(candidate.discovered_job)
    adapter_name = adapter.adapter_name if adapter else "unsupported"

    attempt = ApplicationSubmissionAttempt(
        user_id=user.id,
        auto_apply_candidate_id=candidate.id,
        application_id=application.id,
        application_package_id=package.id,
        adapter_name=adapter_name,
        status="Started",
        started_at=now,
    )
    db.session.add(attempt)
    db.session.flush()
    candidate.last_submission_attempt_at = now

    if adapter is None:
        result = {
            "status": "Unsupported",
            "message": "This application host does not have a Jobfinitum submission adapter yet.",
            "detail": {},
        }
    else:
        file_path = resume_path(candidate.resume)
        if not os.path.isfile(file_path):
            result = {
                "status": "Needs User Action",
                "message": "The selected resume file is not available on this server.",
                "detail": {},
            }
        else:
            result = adapter.submit(
                job=candidate.discovered_job,
                identity=identity,
                application_email=(
                    package.application_email
                    or user.email
                ),
                resume_path=file_path,
                cover_letter_text=(
                    package.cover_letter_text
                ),
                resume_mode=resume_mode,
                application_answers=application_answers(
                    package.answers_json
                ),
            )

    status = result.get("status") or "Failed"
    message = result.get("message") or "Submission attempt failed."
    detail = result.get("detail") or {}

    if (
        status == "Needs Application Answer"
        and isinstance(detail.get("questions"), list)
    ):
        question_state = merge_questions(
            package.answers_json,
            detail["questions"],
        )
        package.answers_json = dump_question_state(
            question_state
        )

    attempt.status = status
    attempt.message = message
    attempt.detail_json = json.dumps(detail, sort_keys=True)
    attempt.confirmation_reference = result.get("confirmation_reference")
    attempt.confirmation_url = result.get("confirmation_url")
    attempt.finished_at = utcnow_naive()
    candidate.execution_status = status

    if status == "Submitted":
        application.status = "Applied"
        application.application_date = utcnow_naive()
        package.status = "Submitted"
        package.submitted_at = utcnow_naive()
        package.confirmation_reference = result.get("confirmation_reference")
        package.confirmation_url = result.get("confirmation_url")
        package.failure_reason = None
        category = "success"
    elif status in {
        "Waiting for Verification",
        "Waiting for Sign-In",
        "Needs Application Answer",
        "Needs User Action",
    }:
        application.status = (
            f"Auto Apply - {status}"
        )
        package.status = status
        package.failure_reason = message
        category = "warning"
    elif status == "Unsupported":
        application.status = "Auto Apply - Unsupported"
        package.status = "Unsupported"
        package.failure_reason = message
        category = "warning"
    else:
        application.status = "Auto Apply - Failed"
        package.status = "Failed"
        package.failure_reason = message
        category = "danger"

    return {"status": status, "message": message, "category": category}

def mark_candidate_submitted_manually(candidate, user):
    access = get_auto_apply_access(user)

    if not access["allowed"]:
        return {
            "status": "Failed",
            "message": "Auto Apply is not enabled for this account tier.",
            "category": "danger",
        }

    if candidate.execution_status == "Submitted":
        return {
            "status": "Submitted",
            "message": "This application is already marked submitted.",
            "category": "info",
        }

    now = utcnow_naive()

    application = get_or_create_application(candidate)
    package = get_or_create_package(candidate, application)

    previous_status = application.status

    attempt = ApplicationSubmissionAttempt(
        user_id=user.id,
        auto_apply_candidate_id=candidate.id,
        application_id=application.id,
        application_package_id=package.id,
        adapter_name="manual_handoff",
        status="Submitted",
        message=(
            "User confirmed manual submission after "
            "Auto Apply handoff."
        ),
        detail_json=json.dumps(
            {
                "completion_mode": "manual_handoff",
                "previous_execution_status": candidate.execution_status,
            },
            sort_keys=True,
        ),
        started_at=now,
        finished_at=now,
    )

    db.session.add(attempt)

    candidate.status = "Approved"
    candidate.execution_status = "Submitted"
    candidate.reviewed_at = candidate.reviewed_at or now
    candidate.last_submission_attempt_at = now

    application.status = "Applied"
    application.application_date = now

    package.status = "Submitted"
    package.submitted_at = now
    package.failure_reason = None

    if not package.confirmation_reference:
        package.confirmation_reference = (
            "Manual completion confirmed in Jobfinitum"
        )

    db.session.add(
        ApplicationHistory(
            application_id=application.id,
            status="Applied",
            note=(
                "Auto Apply manual handoff completed"
                if previous_status != "Applied"
                else "Manual submission reconfirmed"
            ),
        )
    )

    return {
        "status": "Submitted",
        "message": (
            "Application marked submitted. Jobfinitum recorded "
            "the manual handoff and updated the application tracker."
        ),
        "category": "success",
    }


def reset_candidate_submission(candidate):
    candidate.status = "Pending Review"
    candidate.execution_status = "Not Started"
    candidate.reviewed_at = None

    application = (
        db.session.get(
            JobApplication,
            candidate.application_id,
        )
        if candidate.application_id
        else None
    )

    package = (
        db.session.get(
            ApplicationPackage,
            candidate.application_package_id,
        )
        if candidate.application_package_id
        else None
    )

    if (
        application is not None
        and application.status != "Applied"
    ):
        application.status = "Auto Apply - Preparing"

    if (
        package is not None
        and package.status != "Submitted"
    ):
        package.status = "Prepared"
        package.failure_reason = None

    return {
        "status": "Not Started",
        "message": (
            "Candidate returned to Pending Review. "
            "Previous submission-attempt history was preserved."
        ),
        "category": "info",
    }
