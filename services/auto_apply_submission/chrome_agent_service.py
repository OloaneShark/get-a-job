import re
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



from services.phone_service import (
    country_region_from_name,
    split_phone_for_form,
)

TOKEN_SALT = "jobfinitum-chrome-agent-v1"
TOKEN_MAX_AGE_SECONDS = 1800

LEVER_HOSTS = {
    "jobs.lever.co",
    "jobs.eu.lever.co",
}

GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
}

HIMALAYAS_HOSTS = {
    "himalayas.app",
    "www.himalayas.app",
}

SUPPORTED_HOSTS = (
    LEVER_HOSTS
    | GREENHOUSE_HOSTS
    | HIMALAYAS_HOSTS
)


def utcnow_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def chrome_agent_target(job):
    return str(job.apply_url or job.posting_url or "").strip()


def chrome_agent_supports_job(job):
    host = (
        urlsplit(
            chrome_agent_target(job)
        ).hostname
        or ""
    ).lower()

    return host in SUPPORTED_HOSTS


def chrome_agent_adapter(job):
    host = (
        urlsplit(
            chrome_agent_target(job)
        ).hostname
        or ""
    ).lower()

    if host in LEVER_HOSTS:
        return "lever_hosted"

    if host in GREENHOUSE_HOSTS:
        return "greenhouse_hosted"

    if host in HIMALAYAS_HOSTS:
        return "himalayas_resolver"

    raise ValueError(
        "The Chrome Agent does not support "
        "this application host yet."
    )


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

    adapter_name = chrome_agent_adapter(
        candidate.discovered_job
    )

    preferred_phone_region = country_region_from_name(
        identity.country
    )

    phone_country_iso, phone_national = split_phone_for_form(
        identity.phone,
        preferred_region=preferred_phone_region,
    )

    return {
        "version": 1,
        "executor": "chrome_agent",
        "adapter": adapter_name,
        "candidate_id": candidate.id,
        "target_url": prepared["target"],
        "identity": {
            "first_name": identity.first_name,
            "last_name": identity.last_name,
            "full_name": f"{identity.first_name} {identity.last_name}".strip(),
            "email": package.application_email or user.email,
            "phone": identity.phone or "",
            "phone_e164": identity.phone or "",
            "phone_country_iso": phone_country_iso or "",
            "phone_country_name": identity.country or "",
            "phone_national": phone_national or "",
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


def _normalize_agent_questions(
    raw_questions,
    adapter_name,
):
    result = []

    for raw in raw_questions or []:
        if not isinstance(raw, dict):
            continue

        field_name = str(
            raw.get("field_name")
            or ""
        ).strip()

        text = " ".join(
            str(
                raw.get("text")
                or ""
            ).split()
        ).strip()

        if not text:
            continue

        question_type = str(
            raw.get("type")
            or "text"
        ).strip()

        choices = raw.get("choices")

        if not isinstance(
            choices,
            list,
        ):
            choices = []

        result.append(
            {
                "key": build_question_key(
                    adapter_name,
                    field_name,
                    text,
                ),
                "field_name": field_name,
                "text": text,
                "type": question_type,
                "required": bool(
                    raw.get(
                        "required",
                        True,
                    )
                ),
                "choices": choices,
                "adapter": adapter_name,
            }
        )

    return result



def _known_profile_answer_for_agent_question(identity, question):
    text = " ".join(
        str(question.get("text") or "").lower().split()
    )
    field_name = str(
        question.get("field_name") or ""
    ).strip().lower()

    def matches(*parts):
        return any(
            part in text or part in field_name
            for part in parts
        )

    def generic_total_experience_question():
        normalized = re.sub(
            r"[^a-z0-9]+",
            " ",
            text,
        ).strip()

        patterns = (
            r"^years of experience$",
            r"^total years of experience$",
            r"^how many years of experience do you have$",
            r"^how many total years of experience do you have$",
            r"^how many years of professional experience do you have$",
            r"^how many years of work experience do you have$",
            r"^what are your total years of experience$",
            r"^what is your total years of experience$",
        )

        return any(
            re.fullmatch(pattern, normalized)
            for pattern in patterns
        )

    if matches("linkedin"):
        return identity.linkedin_url or None

    if matches("github"):
        return identity.github_url or None

    if matches("website", "portfolio"):
        return identity.website_url or None

    if (
        text in ("location (city)", "location city", "city")
        or field_name in ("location", "location_city", "city")
    ):
        return identity.city or None

    if matches(
        "salary expectation",
        "salary expectations",
        "desired salary",
        "expected salary",
        "compensation expectation",
        "desired compensation",
        "base salary expectation",
    ):
        return identity.salary_expectation or None

    if matches(
        "18 years of age",
        "18 or older",
        "at least 18",
    ):
        if identity.is_18_or_older is True:
            return "Yes"
        if identity.is_18_or_older is False:
            return "No"

    if matches(
        "authorized to work",
        "authorization to work",
        "work authorization",
        "eligible to work",
    ):
        return identity.work_authorization_default or None

    if matches(
        "require sponsorship",
        "need sponsorship",
        "visa sponsorship",
        "sponsorship now",
        "sponsorship now, or in the future",
    ):
        return identity.sponsorship_default or None

    if (
        generic_total_experience_question()
        and identity.years_of_experience is not None
    ):
        return str(identity.years_of_experience)

    return None



def _compatible_profile_answer_for_question(question, answer):
    if answer in (None, "", [], ()):
        return None

    choices = question.get("choices") or []

    if not choices:
        return answer

    wanted = str(answer).strip().lower()

    if not wanted:
        return None

    for choice in choices:
        if isinstance(choice, dict):
            label = str(
                choice.get("label") or ""
            ).strip()
            value = str(
                choice.get("value")
                or choice.get("platform_value")
                or ""
            ).strip()

            if (
                label.lower() == wanted
                or value.lower() == wanted
            ):
                return label or value
        else:
            value = str(choice or "").strip()

            if value.lower() == wanted:
                return value

    return None

def _record_himalayas_manual_handoff(
    *,
    candidate,
    user,
    application,
    package,
    message,
    detail,
    resolved_url=None,
    resolved_host=None,
):
    now = utcnow_naive()

    normalized_detail = dict(detail or {})
    normalized_detail.update(
        {
            "resolver": "himalayas_browser_agent",
            "manual_application": True,
        }
    )

    if resolved_url:
        normalized_detail["resolved_url"] = resolved_url

    if resolved_host:
        normalized_detail["resolved_host"] = resolved_host

    attempt = ApplicationSubmissionAttempt(
        user_id=user.id,
        auto_apply_candidate_id=candidate.id,
        application_id=application.id,
        application_package_id=package.id,
        adapter_name="himalayas_resolver",
        status="Unsupported",
        message=message,
        detail_json=json.dumps(
            normalized_detail,
            sort_keys=True,
        ),
        started_at=now,
        finished_at=now,
    )
    db.session.add(attempt)

    candidate.last_submission_attempt_at = now
    candidate.execution_status = "Unsupported"

    application.status = "Auto Apply - Unsupported"

    package.status = "Unsupported"
    package.failure_reason = message

    return {
        "status": "Unsupported",
        "message": message,
        "resolved_url": resolved_url,
        "resolved_host": resolved_host,
        "continue_in_chrome_agent": False,
        "manual_application": True,
    }


def apply_chrome_agent_result(candidate, user, payload):
    prepared = prepare_chrome_agent_candidate(candidate, user)
    if not prepared["ok"]:
        raise ValueError(prepared["message"])

    application = prepared["application"]
    package = prepared["package"]
    identity = prepared["identity"]

    adapter_name = chrome_agent_adapter(
        candidate.discovered_job
    )

    if adapter_name == "himalayas_resolver":
        resolver_status = str(
            payload.get("status") or ""
        ).strip().lower()

        if resolver_status == "needs_manual_destination":
            detail = payload.get("detail")

            if not isinstance(detail, dict):
                detail = {}

            message = str(
                payload.get("message")
                or (
                    "Himalayas did not expose the employer "
                    "application destination automatically."
                )
            ).strip()

            return _record_himalayas_manual_handoff(
                candidate=candidate,
                user=user,
                application=application,
                package=package,
                message=message,
                detail=detail,
                resolved_url=None,
                resolved_host=None,
            )

        if resolver_status != "resolved_application_target":
            raise ValueError(
                "Himalayas Browser Agent did not return "
                "a resolved employer application target."
            )

        resolved_url = str(
            payload.get("resolved_url")
            or payload.get("application_url")
            or ""
        ).strip()

        resolved_parts = urlsplit(resolved_url)
        resolved_host = (
            resolved_parts.hostname or ""
        ).lower()

        if (
            resolved_parts.scheme not in {"http", "https"}
            or not resolved_host
            or resolved_host in HIMALAYAS_HOSTS
        ):
            raise ValueError(
                "Himalayas Browser Agent returned an "
                "invalid external application target."
            )

        job = candidate.discovered_job
        job.apply_url = resolved_url
        db.session.flush()

        continue_in_chrome_agent = (
            chrome_agent_supports_job(job)
            and chrome_agent_adapter(job)
            != "himalayas_resolver"
        )

        resolved_adapter = None

        if continue_in_chrome_agent:
            resolved_adapter = chrome_agent_adapter(job)

        if not continue_in_chrome_agent:
            return _record_himalayas_manual_handoff(
                candidate=candidate,
                user=user,
                application=application,
                package=package,
                message=(
                    "Himalayas resolved this application to "
                    f"{resolved_host}, which does not have a "
                    "Jobfinitum Auto Apply adapter yet. Continue "
                    "from Manual Apply."
                ),
                detail=(
                    payload.get("detail")
                    if isinstance(
                        payload.get("detail"),
                        dict,
                    )
                    else {}
                ),
                resolved_url=resolved_url,
                resolved_host=resolved_host,
            )

        return {
            "status": "Resolved Application Target",
            "message": (
                "Himalayas employer application "
                "target resolved."
            ),
            "resolved_url": resolved_url,
            "resolved_host": resolved_host,
            "resolved_adapter": resolved_adapter,
            "continue_in_chrome_agent": (
                continue_in_chrome_agent
            ),
        }

    platform_name = (
        "Lever"
        if adapter_name == "lever_hosted"
        else "Greenhouse"
        if adapter_name == "greenhouse_hosted"
        else "application host"
    )

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
        "Submitted": (
            "Chrome Agent submitted the "
            f"{platform_name} application successfully."
        ),
        "Waiting for Verification": (
            f"{platform_name} requires human "
            "verification in normal Chrome."
        ),
        "Needs Application Answer": (
            f"{platform_name} requires additional "
            "application answers."
        ),
        "Needs User Action": (
            f"{platform_name} requires additional "
            "user action."
        ),
        "Failed": (
            "Chrome Agent submission failed."
        ),
    }
    message = str(
        payload.get("message") or default_messages[status]
    ).strip()

    detail = payload.get("detail")
    if not isinstance(detail, dict):
        detail = {}

    if status == "Needs Application Answer":
        all_questions = _normalize_agent_questions(
            payload.get("questions"),
            str(
                (
                    payload.get("detail")
                    or {}
                ).get("adapter")
                or payload.get("adapter")
                or "greenhouse_hosted"
            ),
        )

        if all_questions:
            state = merge_questions(
                package.answers_json,
                all_questions,
                preserve_existing=True,
            )

            answers = dict(
                state.get("answers")
                or {}
            )

            profile_prefilled = []

            for question in all_questions:
                key = str(
                    question.get("key")
                    or ""
                )

                if not key:
                    continue

                existing = answers.get(key)

                if existing not in (
                    None,
                    "",
                    [],
                    (),
                ):
                    continue

                known_answer = (
                    _known_profile_answer_for_agent_question(
                        identity,
                        question,
                    )
                )

                compatible_answer = (
                    _compatible_profile_answer_for_question(
                        question,
                        known_answer,
                    )
                )

                if compatible_answer in (
                    None,
                    "",
                    [],
                    (),
                ):
                    continue

                answers[key] = compatible_answer

                profile_prefilled.append(
                    {
                        "key": key,
                        "text": question.get("text"),
                    }
                )

            state["answers"] = answers

            package.answers_json = dump_question_state(
                state
            )

            if profile_prefilled:
                detail[
                    "profile_prefilled_questions"
                ] = profile_prefilled

            status = "Needs Application Answer"

            message = (
                payload.get("message")
                or "Greenhouse identified required fields that still need attention."
            )

    now = utcnow_naive()
    confirmation_url = str(
        payload.get("confirmation_url") or ""
    ).strip() or None

    attempt = ApplicationSubmissionAttempt(
        user_id=user.id,
        auto_apply_candidate_id=candidate.id,
        application_id=application.id,
        application_package_id=package.id,
        adapter_name=(
            adapter_name.replace(
                "_hosted",
                "",
            )
            + "_chrome_agent"
        ),
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
