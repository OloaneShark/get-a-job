"""Bounded, answer-free diagnostics shared by browser reports and the queue."""

import json
from hashlib import sha256
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


REASONS = {
    "submitted": ("submission_confirmed", "Submission confirmed", "confirmation"),
    "waiting_verification": ("captcha_visible", "Human verification required", "verification"),
    "waiting_sign_in": ("sign_in_required", "Employer sign-in required", "sign_in"),
    "needs_application_answer": ("answer_required", "Application answers required", "filling"),
    "needs_user_action": ("user_action_required", "Application needs attention", "validation"),
    "unsupported": ("unsupported_form", "Manual application required", "form_detection"),
    "failed": ("agent_error", "Browser Agent failed", "unknown"),
    "posting_closed": ("listing_closed", "Job is no longer available", "navigation"),
    "closed": ("listing_closed", "Job is no longer available", "navigation"),
    "needs_manual_destination": ("destination_not_found", "Employer destination unavailable", "resolving"),
    "resolved_application_target": ("destination_resolved", "Employer destination found", "resolving"),
    "retrying_with_saved_answers": ("saved_answer_retry", "Retrying saved answers", "filling"),
    "rejected": ("candidate_rejected", "Application was rejected from the queue", "stopped"),
    "stopped": ("user_stopped", "Stopped by user", "stopped"),
}


def diagnostic_run_id(token):
    return sha256(str(token).encode("utf-8")).hexdigest()[:32]


def safe_url(value):
    try:
        parts = urlsplit(str(value or "")[:4000])
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return ""
        # Keep job identifiers, never launch tokens, credentials, or personal data.
        query = urlencode([
            (key, item) for key, item in parse_qsl(parts.query)
            if key.lower() in {"gh_jid", "jobid", "job_id", "jid", "for"}
        ])
        host = parts.hostname
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, query, ""))[:2000]
    except ValueError:
        return ""


def bounded_number(value, maximum):
    try:
        return max(0, min(maximum, int(value))) if value is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def field_names(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        str(item)[:200] for item in value[:50] if isinstance(item, str) and item.strip()
    ))


def normalize_diagnostics(status, detail=None, *, adapter="", url="", message=""):
    detail = detail if isinstance(detail, dict) else {}
    raw = detail.get("diagnostics")
    raw = raw if isinstance(raw, dict) else {}
    status_key = str(status or "").strip().lower().replace(" ", "_")
    code, label, phase = REASONS.get(status_key, ("unknown_result", "Result needs review", "unknown"))
    failed_fields = field_names(detail.get("uncommitted_fields"))
    missing_controls = field_names(detail.get("missing_controls"))
    required_fields = field_names(detail.get("required_fields"))
    reason = str(detail.get("reason") or "").lower()
    if status_key == "retrying_with_saved_answers":
        code, label, phase = REASONS[status_key]
    elif reason in {"batch_result_timeout", "batch_watchdog_timeout"}:
        code, label, phase = "runner_timeout", "Browser Agent stopped reporting", "unknown"
    elif failed_fields:
        code, label, phase = "field_not_persisted", "Answers did not stay selected", "validation"
    elif missing_controls:
        code, label, phase = "field_not_found", "Required controls were not found", "filling"
    elif detail.get("cache_hit"):
        code, label, phase = "cached_unsupported_host", "Previously unsupported employer", "resolving"
    elif detail.get("manual_application") and detail.get("resolved_host"):
        code, label, phase = "unsupported_destination", "Employer system is not supported", "resolving"
    elif reason in {"resume_upload_failed", "missing_resume_field"}:
        code, label, phase = reason, "Resume upload could not be confirmed", "resume_upload"
    elif reason == "submission_confirmation_timeout":
        code, label, phase = "submission_unconfirmed", "Submission could not be confirmed", "confirmation"
    elif "timeout" in reason or (
        status_key == "needs_manual_destination" and "timed out" in str(message).lower()
    ):
        code, label, phase = "resolver_timeout", "Employer lookup timed out", "resolving"
    elif status_key in {"needs_user_action", "failed"} and (
        "confirm" in str(message).lower() and "submi" in str(message).lower()
    ):
        code, label, phase = "submission_unconfirmed", "Submission could not be confirmed", "confirmation"

    observed_phase = str(raw.get("phase") or "")
    if code in {"runner_timeout", "agent_error", "unknown_result", "user_action_required"} and observed_phase in {"form_detection", "resolving", "filling", "resume_upload", "submitting", "confirmation", "verification", "sign_in", "validation"}:
        phase = observed_phase
    return {
        "schema_version": 1,
        "reason_code": code,
        "reason_label": label,
        "phase": phase,
        "adapter": str(adapter or raw.get("adapter") or detail.get("adapter") or detail.get("resolver") or "unknown")[:80],
        "url": safe_url(
            detail.get("url") or detail.get("final_url") or detail.get("resolved_url")
            or raw.get("url") or url
        ),
        "failed_fields": failed_fields or missing_controls or required_fields,
        "elapsed_ms": bounded_number(raw.get("elapsed_ms"), 86400000),
        "retry_count": bounded_number(raw.get("retry_count"), 100),
        "agent_version": str(raw.get("agent_version") or "")[:30],
        "run_id": str(raw.get("run_id") or "")[:64],
        "batch": raw.get("batch") is True,
        "tab_outcome": "not_reported",
        "batch_outcome": "not_reported" if raw.get("batch") is True else "not_running",
    }


def attempt_diagnostics(attempt):
    if attempt is None:
        return None
    try:
        detail = json.loads(attempt.detail_json or "{}")
    except (TypeError, ValueError):
        detail = {}
    if not isinstance(detail, dict):
        detail = {}
    diagnostic = detail.get("diagnostics")
    if isinstance(diagnostic, dict) and diagnostic.get("schema_version") == 1:
        return diagnostic
    # Historical attempts never claim tab or timing observations they did not record.
    return normalize_diagnostics(
        attempt.status, detail, adapter=attempt.adapter_name, message=attempt.message,
    )


def update_receipt(attempt, payload):
    diagnostic = attempt_diagnostics(attempt)
    if not diagnostic or not isinstance(payload, dict):
        raise ValueError("Invalid runner diagnostic receipt.")
    if not diagnostic.get("run_id") or payload.get("run_id") != diagnostic["run_id"]:
        raise ValueError("This receipt belongs to a different runner attempt.")
    for key, choices in {
        "tab_outcome": {"closed", "recycled", "retained", "still_open", "cleanup_failed", "not_observed", "continuing"},
        "batch_outcome": {"advanced", "paused", "stopped", "complete", "retrying", "continuing"},
    }.items():
        if payload.get(key) in choices:
            diagnostic[key] = payload[key]
    detail = json.loads(attempt.detail_json or "{}")
    detail["diagnostics"] = diagnostic
    attempt.detail_json = json.dumps(detail, sort_keys=True)
    return diagnostic
