
import hashlib
import re

from models import ApplicationAnswerMemory, db


SENSITIVE_MEMORY_PHRASES = (
    "race",
    "ethnicity",
    "ethnic",
    "gender",
    "sex assigned",
    "sexual orientation",
    "disability",
    "disabled",
    "veteran",
    "military status",
    "religion",
    "religious",
    "pronoun",
    "demographic",
    "self-identification",
    "self identification",
)


def normalize_memory_question_text(value):
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _canonical_question_family(text):
    normalized = normalize_memory_question_text(text)

    if (
        "authorized to work" in normalized
        and (
            "u.s." in normalized
            or "us" in normalized
            or "united states" in normalized
        )
    ):
        return "work_authorization_us"

    if (
        "sponsorship" in normalized
        and ("work" in normalized or "visa" in normalized)
    ):
        return "work_sponsorship"

    if (
        "18 years" in normalized
        or "18 or older" in normalized
        or "at least 18" in normalized
    ):
        return "age_18"

    if (
        "salary expectation" in normalized
        or "salary expectations" in normalized
        or "expected salary" in normalized
        or "desired salary" in normalized
        or "desired compensation" in normalized
    ):
        return "salary_expectation"

    if "linkedin" in normalized:
        return "linkedin"

    if "github" in normalized:
        return "github"

    if (
        "non-compete" in normalized
        or "non compete" in normalized
        or "restrictive agreement" in normalized
    ):
        return "restrictive_agreements"

    if "agile methodolog" in normalized:
        return "agile_experience"

    if "bachelor" in normalized and "degree" in normalized:
        return "bachelors_degree"

    if "proficiency" in normalized and "python" in normalized:
        return "python_proficiency"

    if (
        "cloud environment" in normalized
        and (
            "aws" in normalized
            or "gcp" in normalized
            or "azure" in normalized
        )
    ):
        return "cloud_deployment_experience"

    if "pharmaceutical" in normalized or "pharma" in normalized:
        return "pharma_experience"

    if (
        "javascript" in normalized
        and "typescript" in normalized
        and "framework" in normalized
    ):
        return "js_ts_frameworks"

    if (
        "years of experience" in normalized
        or "how many years" in normalized
    ):
        return "years_experience"

    if (
        "where are you based" in normalized
        or "where are you located" in normalized
    ):
        return "current_location"

    return None


def answer_memory_key(question_text):
    family = _canonical_question_family(question_text)

    if family:
        raw = "family:" + family
    else:
        raw = "text:" + normalize_memory_question_text(question_text)

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def can_remember_question(question):
    text = normalize_memory_question_text(
        question.get("text")
    )

    if not text:
        return False

    return not any(
        phrase in text
        for phrase in SENSITIVE_MEMORY_PHRASES
    )


def _choice_values(question):
    result = set()

    for choice in question.get("choices") or []:
        if not isinstance(choice, dict):
            continue

        for key in ("value", "label"):
            value = str(
                choice.get(key) or ""
            ).strip()

            if value:
                result.add(value.lower())

    return result


def answer_is_compatible(question, answer):
    choices = question.get("choices") or []

    if not choices:
        return True

    valid = _choice_values(question)

    if not valid:
        return True

    if question.get("type") == "checkbox":
        values = (
            answer
            if isinstance(answer, list)
            else [answer]
        )

        return bool(values) and all(
            str(value or "").strip().lower() in valid
            for value in values
        )

    return (
        str(answer or "").strip().lower()
        in valid
    )


def apply_saved_answer_memories(user_id, state):
    questions = state.get("questions") or []
    answers = dict(state.get("answers") or {})

    memories = {
        memory.question_key: memory
        for memory in (
            ApplicationAnswerMemory.query
            .filter_by(user_id=user_id)
            .all()
        )
    }

    filled_keys = set()

    for question in questions:
        key = str(question.get("key") or "")

        if not key:
            continue

        existing = answers.get(key)

        if existing not in (None, "", [], ()):
            continue

        if not can_remember_question(question):
            continue

        memory = memories.get(
            answer_memory_key(
                question.get("text")
            )
        )

        if memory is None:
            continue

        answer = memory.answer_json

        if not answer_is_compatible(
            question,
            answer,
        ):
            continue

        answers[key] = answer
        filled_keys.add(key)

    state = dict(state)
    state["answers"] = answers
    state["remembered_keys"] = sorted(
        filled_keys
    )

    return state


def answer_memories_for_agent(user_id):
    memories = (
        ApplicationAnswerMemory.query
        .filter_by(user_id=user_id)
        .order_by(
            ApplicationAnswerMemory.updated_at.desc(),
            ApplicationAnswerMemory.id.desc(),
        )
        .all()
    )

    return [
        {
            "question_text": memory.question_text or "",
            "question_type": memory.question_type or None,
            "answer": memory.answer_json,
        }
        for memory in memories
        if memory.question_text
    ]


def remember_submitted_answers(
    user_id,
    questions,
    submitted_answers,
    remember_keys,
):
    remember_keys = {
        str(key)
        for key in remember_keys
        if str(key)
    }

    question_by_key = {
        str(question.get("key") or ""): question
        for question in questions
        if isinstance(question, dict)
    }

    saved = 0

    for key in remember_keys:
        question = question_by_key.get(key)

        if (
            question is None
            or not can_remember_question(question)
        ):
            continue

        answer = submitted_answers.get(key)

        if answer in (None, "", [], ()):
            continue

        memory_key = answer_memory_key(
            question.get("text")
        )

        memory = (
            ApplicationAnswerMemory.query
            .filter_by(
                user_id=user_id,
                question_key=memory_key,
            )
            .first()
        )

        if memory is None:
            memory = ApplicationAnswerMemory(
                user_id=user_id,
                question_key=memory_key,
                question_text=(
                    question.get("text")
                    or ""
                ),
            )
            db.session.add(memory)

        memory.question_text = (
            question.get("text")
            or ""
        )
        memory.question_type = (
            question.get("type")
            or None
        )
        memory.answer_json = answer
        saved += 1

    return saved
