import hashlib
import json
import re


QUESTION_STATE_VERSION = 1


def normalize_question_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def build_question_key(adapter_name, field_name, question_text):
    raw = "|".join(
        [
            str(adapter_name or ""),
            str(field_name or ""),
            normalize_question_text(question_text).lower(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def empty_question_state():
    return {
        "version": QUESTION_STATE_VERSION,
        "questions": [],
        "answers": {},
    }


def load_question_state(raw_json):
    if not raw_json:
        return empty_question_state()

    try:
        payload = json.loads(raw_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return empty_question_state()

    if not isinstance(payload, dict):
        return empty_question_state()

    questions = payload.get("questions")
    answers = payload.get("answers")

    if not isinstance(questions, list):
        questions = []

    if not isinstance(answers, dict):
        answers = {}

    return {
        "version": QUESTION_STATE_VERSION,
        "questions": questions,
        "answers": answers,
    }


def dump_question_state(state):
    return json.dumps(
        {
            "version": QUESTION_STATE_VERSION,
            "questions": state.get("questions") or [],
            "answers": state.get("answers") or {},
        },
        sort_keys=True,
    )


def application_answers(raw_json):
    return load_question_state(raw_json)["answers"]


def merge_questions(
    raw_json,
    questions,
):
    state = load_question_state(
        raw_json
    )

    clean_questions = []

    for question in (
        questions or []
    ):
        if not isinstance(
            question,
            dict,
        ):
            continue

        key = question.get(
            "key"
        )

        text = normalize_question_text(
            question.get(
                "text"
            )
        )

        if not key or not text:
            continue

        clean_questions.append(
            {
                "key": str(key),
                "text": text,
                "type": str(
                    question.get(
                        "type"
                    )
                    or "text"
                ),
                "required": bool(
                    question.get(
                        "required",
                        True,
                    )
                ),
                "choices": (
                    question.get(
                        "choices"
                    )
                    if isinstance(
                        question.get(
                            "choices"
                        ),
                        list,
                    )
                    else []
                ),
                "adapter": str(
                    question.get(
                        "adapter"
                    )
                    or ""
                ),
            }
        )

    # A fresh adapter scrape is the authoritative question
    # snapshot for this application package. This replaces
    # malformed/stale labels from older extraction code.
    state["questions"] = clean_questions

    valid_keys = {
        question["key"]
        for question in clean_questions
    }

    state["answers"] = {
        key: value
        for key, value in state[
            "answers"
        ].items()
        if key in valid_keys
    }

    return state

def save_answers(raw_json, answers):
    state = load_question_state(raw_json)

    for key, value in (answers or {}).items():
        if isinstance(value, list):
            cleaned = [
                str(item).strip()
                for item in value
                if str(item).strip()
            ]

            if cleaned:
                state["answers"][str(key)] = cleaned
            else:
                state["answers"].pop(str(key), None)

            continue

        cleaned = str(value or "").strip()

        if cleaned:
            state["answers"][str(key)] = cleaned
        else:
            state["answers"].pop(str(key), None)

    return state
