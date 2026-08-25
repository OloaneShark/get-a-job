import json
import mimetypes
import os
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import ApplicantProfile, ApplicationSubmissionAttempt, db
from services.auto_apply_service import get_auto_apply_access
from services.auto_apply_submission.application_question_service import (
    build_question_key,
    dump_question_state,
    load_question_state,
    merge_questions,
)
from services.auto_apply_submission.engine import (
    get_or_create_application,
    get_or_create_package,
    resume_path,
)


TOKEN_SALT = "jobfinitum-chrome-agent-v1"
TOKEN_MAX_AGE_SECONDS = 1800
SUPPORTED_HOSTS = {"jobs.lever.co", "jobs.eu.lever.co"}


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def chrome_agent_target(job):
    return str(job.apply_url or job.posting_url or "").strip()


def chrome_agent_supports_job(job):
    host = (urlsplit(chrome_agent_target(job)).hostname or "").lower()
    return host in SUPPORTED_HOSTS


def _serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt=TOKEN_SALT)


def create_chrome_agent_token(secret_key, candidate_id, user_id):
    return _serializer(secret_key).dumps(
        {"candidate_id": int(candidate_id), "user_id": int(user_id)}
    )


def decode_chrome_agent_token(secret_key, token):
    try:
        payload = _serializer(secret_key).loads(
            token,
            max_age=TOKEN_MAX_AGE_SECONDS,
        )
    except SignatureExpired as error:
        raise ValueError("Chrome Agent launch token expired.") from error
    except BadSignature as error:
        raise ValueError("Chrome Agent launch token is invalid.") from error

    try:
        return {
            "candidate_id": int(payload["candidate_id"]),
            "user_id": int(payload["user_id"]),
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Chrome Agent launch token is malformed.") from error


def build_chrome_agent_launch_url(target, token, bridge_origin):
    target = str(target or "").strip()
    if not target:
        raise ValueError("No application URL is available.")

    parts = urlsplit(target)
    fragment = urlencode(
        {
            "jobfinitum_agent": token,
            "jobfinitum_origin": str(bridge_origin or "").rstrip("/"),
        }
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, fragment)
    )


def prepare_chrome_agent_candidate(candidate, user):
    if not get_auto_apply_access(user)["allowed"]:
        return {
            "ok": False,
            "message": "Auto Apply is not enabled for this account tier.",
        }

    if not chrome_agent_supports_job(candidate.discovered_job):
        return {
            "ok": False,
            "message": "The Chrome Agent does not support this application host yet.",
        }

    identity = ApplicantProfile.query.filter_by(user_id=user.id).first()
    if identity is None:
        return {
            "ok": False,
            "message": "Save your Applicant Profile before using the Chrome Agent.",
        }

    file_path = resume_path(candidate.resume)
    if not os.path.isfile(file_path):
        return {
            "ok": False,
            "message": "The selected resume file is not available on this server.",
        }

    application = get_or_create_application(candidate)
    package = get_or_create_package(candidate, application)

    candidate.status = "Approved"
    candidate.reviewed_at = utcnow_naive()
    db.session.flush()

    return {
        "ok": True,
        "identity": identity,
        "application": application,
        "package": package,
        "resume_path": file_path,
        "target": chrome_agent_target(candidate.discovered_job),
    }


def _iso_date(value):
    if value is None:
        return None
    try:
        return value.isoformat()
    except Exception:
        return str(value)


def build_chrome_agent_task(candidate, user, *, token, resume_url):
    prepared = prepare_chrome_agent_candidate(candidate, user)
    if not prepared["ok"]:
        raise ValueError(prepared["message"])

    identity = prepared["identity"]
    package = prepared["package"]
    state = load_question_state(package.answers_json)

    questions = []
    for question in state.get("questions") or []:
        key = str(question.get("key") or "")
        if not key:
            continue
        questions.append(
            {
                "key": key,
                "field_name": str(question.get("field_name") or ""),
                "text": str(question.get("text") or ""),
                "type": str(question.get("type") or "text"),
                "required": bool(question.get("required", True)),
                "choices": (
                    question.get("choices")
                    if isinstance(question.get("choices"), list)
                    else []
                ),
                "answer": (state.get("answers") or {}).get(key),
            }
        )

    original_filename = (
        candidate.resume.original_filename
        or candidate.resume.filename
        or "resume"
    )
    content_type = (
        mimetypes.guess_type(original_filename)[0]
        or "application/octet-stream"
    )

    location_text = ", ".join(
        str(value).strip()
        for value in (identity.city, identity.state_region, identity.country)
        if str(value or "").strip()
    )

    return {
        "version": 1,
        "executor": "chrome_agent",
        "adapter": "lever_hosted",
        "candidate_id": candidate.id,
        "target_url": prepared["target"],
        "identity": {
            "first_name": identity.first_name,
            "last_name": identity.last_name,
            "full_name": f"{identity.first_name} {identity.last_name}".strip(),
            "email": package.application_email or user.email,
            "phone": identity.phone or "",
            "city": identity.city or "",
            "state_region": identity.state_region or "",
            "country": identity.country or "",
            "postal_code": identity.postal_code or "",
            "location_text": location_text,
            "linkedin_url": identity.linkedin_url or "",
            "github_url": identity.github_url or "",
            "website_url": identity.website_url or "",
        },
        "reusable_answers": {
            "is_18_or_older": identity.is_18_or_older,
            "work_authorization_default": identity.work_authorization_default,
            "sponsorship_default": identity.sponsorship_default,
            "willing_to_relocate": identity.willing_to_relocate,
            "willing_to_travel": identity.willing_to_travel,
            "years_of_experience": identity.years_of_experience,
            "salary_expectation": identity.salary_expectation or "",
            "available_start_date": _iso_date(identity.available_start_date),
        },
        "application_questions": questions,
        "resume": {
            "filename": original_filename,
            "content_type": content_type,
            "url": resume_url,
        },
    }


def _normalize_agent_questions(raw_questions):
    result = []
    for raw in raw_questions or []:
        if not isinstance(raw, dict):
            continue

        field_name = str(raw.get("field_name") or "").strip()
        text = " ".join(str(raw.get("text") or "").split()).strip()
        if not text:
            continue

        question_type = str(raw.get("type") or "text").strip()
        choices = raw.get("choices")
        if not isinstance(choices, list):
            choices = []

        result.append(
            {
                "key": build_question_key(
                    "lever_hosted",
                    field_name,
                    text,
                ),
                "field_name": field_name,
                "text": text,
                "type": question_type,
                "required": bool(raw.get("required", True)),
                "choices": choices,
                "adapter": "lever_hosted",
            }
        )
    return result


def apply_chrome_agent_result(candidate, user, payload):
    prepared = prepare_chrome_agent_candidate(candidate, user)
    if not prepared["ok"]:
        raise ValueError(prepared["message"])

    application = prepared["application"]
    package = prepared["package"]

    status_map = {
        "submitted": "Submitted",
        "waiting_verification": "Waiting for Verification",
        "needs_application_answer": "Needs Application Answer",
        "needs_user_action": "Needs User Action",
        "failed": "Failed",
    }
    status = status_map.get(
        str(payload.get("status") or "").strip().lower()
    )
    if status is None:
        raise ValueError("Chrome Agent returned an unsupported status.")

    default_messages = {
        "Submitted": "Chrome Agent submitted the Lever application successfully.",
        "Waiting for Verification": "Lever requires human verification in normal Chrome.",
        "Needs Application Answer": "Lever requires additional application answers.",
        "Needs User Action": "Lever requires additional user action.",
        "Failed": "Chrome Agent submission failed.",
    }
    message = str(
        payload.get("message") or default_messages[status]
    ).strip()

    detail = payload.get("detail")
    if not isinstance(detail, dict):
        detail = {}

    if status == "Needs Application Answer":
        questions = _normalize_agent_questions(payload.get("questions"))
        state = merge_questions(package.answers_json, questions)
        package.answers_json = dump_question_state(state)

    now = utcnow_naive()
    confirmation_url = str(
        payload.get("confirmation_url") or ""
    ).strip() or None

    attempt = ApplicationSubmissionAttempt(
        user_id=user.id,
        auto_apply_candidate_id=candidate.id,
        application_id=application.id,
        application_package_id=package.id,
        adapter_name="lever_chrome_agent",
        status=status,
        message=message,
        detail_json=json.dumps(detail, sort_keys=True),
        confirmation_url=confirmation_url,
        started_at=now,
        finished_at=now,
    )
    db.session.add(attempt)

    candidate.last_submission_attempt_at = now
    candidate.execution_status = status

    if status == "Submitted":
        application.status = "Applied"
        application.application_date = now
        package.status = "Submitted"
        package.submitted_at = now
        package.confirmation_url = confirmation_url
        package.failure_reason = None
    elif status in {
        "Waiting for Verification",
        "Needs Application Answer",
        "Needs User Action",
    }:
        application.status = f"Auto Apply - {status}"
        package.status = status
        package.failure_reason = message
    else:
        application.status = "Auto Apply - Failed"
        package.status = "Failed"
        package.failure_reason = message

    db.session.flush()
    return {"status": status, "message": message}
