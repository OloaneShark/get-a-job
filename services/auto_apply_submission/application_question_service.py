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
    *,
    preserve_existing=False,
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
                "field_name": str(
                    question.get(
                        "field_name"
                    )
                    or ""
                ),
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

    # Collapse duplicate logical questions emitted by complex ATS widgets.
    # Greenhouse-style select controls can expose both an outer combobox and an
    # inner input for one employer question. Keep the richer descriptor so the
    # user sees one question with its real choices instead of duplicate text
    # inputs.
    deduped_questions = []
    deduped_indexes = {}

    def question_richness(question):
        question_type = str(
            question.get("type")
            or ""
        ).strip().lower()

        choices = (
            question.get("choices")
            if isinstance(
                question.get("choices"),
                list,
            )
            else []
        )

        return (
            len(choices) * 100
            + (
                25
                if question_type
                in {
                    "select",
                    "radio",
                    "checkbox",
                }
                else 0
            )
            + (
                5
                if str(
                    question.get("field_name")
                    or ""
                ).strip()
                else 0
            )
        )

    for question in clean_questions:
        logical_key = (
            str(
                question.get("adapter")
                or ""
            ).strip().lower(),
            normalize_question_text(
                question.get("text")
            ).lower(),
        )

        if not logical_key[1]:
            continue

        existing_index = deduped_indexes.get(
            logical_key
        )

        if existing_index is None:
            deduped_indexes[
                logical_key
            ] = len(
                deduped_questions
            )
            deduped_questions.append(
                question
            )
            continue

        existing = deduped_questions[
            existing_index
        ]

        if (
            question_richness(
                question
            )
            > question_richness(
                existing
            )
        ):
            deduped_questions[
                existing_index
            ] = question

    clean_questions = deduped_questions

    # A fresh adapter scrape is the authoritative question
    # snapshot for this application package. Preserve answers
    # even when two executors produce slightly different keys
    # for the same employer field.
    previous_questions = (
        state.get("questions")
        or []
    )

    previous_answers = dict(
        state.get("answers")
        or {}
    )

    previous_by_field = {}
    previous_by_text = {}

    for previous in previous_questions:
        if not isinstance(
            previous,
            dict,
        ):
            continue

        previous_key = str(
            previous.get("key")
            or ""
        )

        if (
            not previous_key
            or previous_key
            not in previous_answers
        ):
            continue

        previous_adapter = str(
            previous.get("adapter")
            or ""
        ).strip().lower()

        previous_field = str(
            previous.get("field_name")
            or ""
        ).strip().lower()

        previous_text = normalize_question_text(
            previous.get("text")
        ).lower()

        if previous_field:
            previous_by_field[
                (
                    previous_adapter,
                    previous_field,
                )
            ] = previous_answers[
                previous_key
            ]

        if previous_text:
            previous_by_text[
                (
                    previous_adapter,
                    previous_text,
                )
            ] = previous_answers[
                previous_key
            ]

    remapped_answers = {}

    for question in clean_questions:
        key = question["key"]

        if key in previous_answers:
            remapped_answers[key] = (
                previous_answers[key]
            )
            continue

        adapter = str(
            question.get("adapter")
            or ""
        ).strip().lower()

        field_name = str(
            question.get("field_name")
            or ""
        ).strip().lower()

        question_text = normalize_question_text(
            question.get("text")
        ).lower()

        if (
            field_name
            and (
                adapter,
                field_name,
            )
            in previous_by_field
        ):
            remapped_answers[key] = (
                previous_by_field[
                    (
                        adapter,
                        field_name,
                    )
                ]
            )
            continue

        if (
            question_text
            and (
                adapter,
                question_text,
            )
            in previous_by_text
        ):
            remapped_answers[key] = (
                previous_by_text[
                    (
                        adapter,
                        question_text,
                    )
                ]
            )

    if not preserve_existing:
        state["questions"] = clean_questions
        state["answers"] = remapped_answers
        return state

    # Chrome/Browser Agent question handback is PARTIAL:
    # it normally reports only the fields that still need user
    # attention. Never treat that subset as a replacement for
    # the full application-answer package or previously-saved
    # answers will disappear on every retry.
    merged_questions = [
        dict(question)
        for question in previous_questions
        if isinstance(
            question,
            dict,
        )
    ]

    merged_answers = dict(
        previous_answers
    )

    index_by_key = {}
    index_by_field = {}
    index_by_text = {}

    for index, previous in enumerate(
        merged_questions
    ):
        previous_key = str(
            previous.get("key")
            or ""
        )

        previous_adapter = str(
            previous.get("adapter")
            or ""
        ).strip().lower()

        previous_field = str(
            previous.get("field_name")
            or ""
        ).strip().lower()

        previous_text = normalize_question_text(
            previous.get("text")
        ).lower()

        if previous_key:
            index_by_key[
                previous_key
            ] = index

        if previous_field:
            index_by_field[
                (
                    previous_adapter,
                    previous_field,
                )
            ] = index

        if previous_text:
            index_by_text[
                (
                    previous_adapter,
                    previous_text,
                )
            ] = index

    for incoming in clean_questions:
        incoming_key = str(
            incoming.get("key")
            or ""
        )

        incoming_adapter = str(
            incoming.get("adapter")
            or ""
        ).strip().lower()

        incoming_field = str(
            incoming.get("field_name")
            or ""
        ).strip().lower()

        incoming_text = normalize_question_text(
            incoming.get("text")
        ).lower()

        matched_index = None

        if (
            incoming_key
            and incoming_key
            in index_by_key
        ):
            matched_index = (
                index_by_key[
                    incoming_key
                ]
            )

        elif (
            incoming_field
            and (
                incoming_adapter,
                incoming_field,
            )
            in index_by_field
        ):
            matched_index = (
                index_by_field[
                    (
                        incoming_adapter,
                        incoming_field,
                    )
                ]
            )

        elif (
            incoming_text
            and (
                incoming_adapter,
                incoming_text,
            )
            in index_by_text
        ):
            matched_index = (
                index_by_text[
                    (
                        incoming_adapter,
                        incoming_text,
                    )
                ]
            )

        if matched_index is None:
            merged_questions.append(
                incoming
            )

            new_index = (
                len(
                    merged_questions
                )
                - 1
            )

            if incoming_key:
                index_by_key[
                    incoming_key
                ] = new_index

            if incoming_field:
                index_by_field[
                    (
                        incoming_adapter,
                        incoming_field,
                    )
                ] = new_index

            if incoming_text:
                index_by_text[
                    (
                        incoming_adapter,
                        incoming_text,
                    )
                ] = new_index

            if (
                incoming_key
                in remapped_answers
            ):
                merged_answers[
                    incoming_key
                ] = remapped_answers[
                    incoming_key
                ]

            continue

        previous = (
            merged_questions[
                matched_index
            ]
        )

        previous_key = str(
            previous.get("key")
            or ""
        )

        # Keep the freshest descriptor/choice list from the
        # Agent, while preserving the saved answer.
        merged_questions[
            matched_index
        ] = incoming

        if (
            incoming_key
            and incoming_key
            in remapped_answers
        ):
            merged_answers[
                incoming_key
            ] = remapped_answers[
                incoming_key
            ]

        elif (
            previous_key
            and previous_key
            in merged_answers
            and incoming_key
        ):
            merged_answers[
                incoming_key
            ] = merged_answers[
                previous_key
            ]

        if (
            previous_key
            and incoming_key
            and previous_key
            != incoming_key
        ):
            merged_answers.pop(
                previous_key,
                None,
            )

        if previous_key:
            index_by_key.pop(
                previous_key,
                None,
            )

        if incoming_key:
            index_by_key[
                incoming_key
            ] = matched_index

        if incoming_field:
            index_by_field[
                (
                    incoming_adapter,
                    incoming_field,
                )
            ] = matched_index

        if incoming_text:
            index_by_text[
                (
                    incoming_adapter,
                    incoming_text,
                )
            ] = matched_index

    valid_keys = {
        str(
            question.get("key")
            or ""
        )
        for question in merged_questions
        if isinstance(
            question,
            dict,
        )
        and str(
            question.get("key")
            or ""
        )
    }

    merged_answers = {
        key: value
        for key, value
        in merged_answers.items()
        if key in valid_keys
    }

    state["questions"] = (
        merged_questions
    )

    state["answers"] = (
        merged_answers
    )

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
