import re


YES_NO_UNKNOWN = {
    "yes": "Yes",
    "no": "No",
    "unknown": "Unknown",
}


def normalize_question(value):
    return re.sub(
        r"\s+",
        " ",
        str(value or "")
        .strip()
        .lower(),
    )


def _configured_yes_no(value):
    normalized = str(
        value or "Unknown"
    ).strip().lower()

    if normalized not in {
        "yes",
        "no",
    }:
        return None

    return YES_NO_UNKNOWN[
        normalized
    ]


def get_application_answer(
    identity,
    question_text,
):
    question = normalize_question(
        question_text
    )

    if not question:
        return None

    rules = [
        (
            "is_18_or_older",
            (
                "18 or older",
                "18 years of age or older",
                "at least 18",
                "minimum age requirement",
                "over the age of 18",
            ),
            getattr(
                identity,
                "is_18_or_older",
                "Unknown",
            ),
        ),
        (
            "work_authorization_default",
            (
                "authorized to work",
                "legally authorized to work",
                "eligible to work",
                "work authorization",
            ),
            getattr(
                identity,
                "work_authorization_default",
                "Unknown",
            ),
        ),
        (
            "sponsorship_default",
            (
                "require sponsorship",
                "requires sponsorship",
                "need sponsorship",
                "visa sponsorship",
                "immigration sponsorship",
            ),
            getattr(
                identity,
                "sponsorship_default",
                "Unknown",
            ),
        ),
        (
            "willing_to_relocate",
            (
                "willing to relocate",
                "open to relocation",
                "able to relocate",
            ),
            getattr(
                identity,
                "willing_to_relocate",
                "Unknown",
            ),
        ),
        (
            "willing_to_travel",
            (
                "willing to travel",
                "able to travel",
                "open to travel",
            ),
            getattr(
                identity,
                "willing_to_travel",
                "Unknown",
            ),
        ),
        (
            "currently_residing_in_japan",
            (
                "currently reside in japan",
                "currently residing in japan",
                "current resident of japan",
                "currently live in japan",
            ),
            getattr(
                identity,
                "currently_residing_in_japan",
                "Unknown",
            ),
        ),
    ]

    for key, patterns, raw_value in rules:
        if not any(
            pattern in question
            for pattern in patterns
        ):
            continue

        value = _configured_yes_no(
            raw_value
        )

        if value is None:
            return None

        return {
            "key": key,
            "type": "yes_no",
            "value": value,
        }

    language_rules = [
        (
            "japanese_proficiency",
            (
                "japanese proficiency",
                "japanese language level",
                "level of japanese",
                "fluency in japanese",
                "fluent in japanese",
                "speak japanese fluently",
                "japanese ability",
                "how well do you speak japanese",
            ),
            getattr(
                identity,
                "japanese_proficiency",
                "Unknown",
            ),
        ),
        (
            "english_proficiency",
            (
                "english proficiency",
                "english language level",
                "level of english",
                "fluency in english",
                "fluent in english",
                "speak english fluently",
                "english ability",
                "how well do you speak english",
            ),
            getattr(
                identity,
                "english_proficiency",
                "Unknown",
            ),
        ),
    ]

    for key, patterns, raw_value in language_rules:
        if not any(
            pattern in question
            for pattern in patterns
        ):
            continue

        value = str(
            raw_value or ""
        ).strip()

        if (
            not value
            or value.lower() == "unknown"
        ):
            return None

        return {
            "key": key,
            "type": "text",
            "value": value,
        }

    if any(
        pattern in question
        for pattern in (
            "years of experience",
            "how many years",
            "years experience",
        )
    ):
        value = getattr(
            identity,
            "years_of_experience",
            None,
        )

        if value is not None:
            return {
                "key": "years_of_experience",
                "type": "number",
                "value": str(value),
            }

    if any(
        pattern in question
        for pattern in (
            "salary expectation",
            "salary expectations",
            "desired salary",
            "expected salary",
            "compensation expectation",
            "compensation expectations",
            "desired compensation",
        )
    ):
        value = (
            getattr(
                identity,
                "salary_expectation",
                None,
            )
            or ""
        ).strip()

        if value:
            return {
                "key": "salary_expectation",
                "type": "text",
                "value": value,
            }

    if any(
        pattern in question
        for pattern in (
            "available to start",
            "availability to start",
            "start date",
            "earliest start",
            "earliest available",
        )
    ):
        value = getattr(
            identity,
            "available_start_date",
            None,
        )

        if value is not None:
            return {
                "key": "available_start_date",
                "type": "date",
                "value": value.isoformat(),
            }

    return None
