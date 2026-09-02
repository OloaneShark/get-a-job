import os
import re
from functools import lru_cache

import requests


GREENHOUSE_EDUCATION_BASE_URL = "https://boards.greenhouse.io"
DEFAULT_GREENHOUSE_BOARD_TOKEN = (
    os.getenv("GREENHOUSE_EDUCATION_BOARD_TOKEN", "").strip()
    or "li-thermal-works"
)
GREENHOUSE_BOARD_TOKEN_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{1,100}$"
)


class GreenhouseEducationLookupError(RuntimeError):
    pass


def _normalize_query(value):
    query = " ".join(str(value or "").split())

    if len(query) < 3:
        raise ValueError(
            "Enter at least 3 characters to search for a school."
        )

    return query[:100]


def _board_tokens(values):
    tokens = []
    seen = set()

    for value in [
        *(values or []),
        DEFAULT_GREENHOUSE_BOARD_TOKEN,
    ]:
        token = str(value or "").strip()
        normalized = token.casefold()

        if (
            not GREENHOUSE_BOARD_TOKEN_PATTERN.fullmatch(token)
            or normalized in seen
        ):
            continue

        seen.add(normalized)
        tokens.append(token)

    return tuple(tokens)


@lru_cache(maxsize=512)
def _cached_school_search(query, board_tokens):
    for token in board_tokens:
        url = (
            f"{GREENHOUSE_EDUCATION_BASE_URL}/v1/boards/"
            f"{token}/education/schools"
        )

        try:
            response = requests.get(
                url,
                params={
                    "term": query,
                    "page": 1,
                },
                headers={
                    "Accept": "application/json",
                    "User-Agent": "Jobfinitum/1.0",
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            continue

        items = payload.get("items") if isinstance(payload, dict) else None

        if not isinstance(items, list):
            continue

        schools = []
        seen_labels = set()

        for item in items:
            if not isinstance(item, dict):
                continue

            label = str(
                item.get("text")
                or item.get("label")
                or item.get("value")
                or ""
            ).strip()
            normalized_label = label.casefold()

            if not label or normalized_label in seen_labels:
                continue

            seen_labels.add(normalized_label)
            schools.append({
                "id": str(item.get("id") or label),
                "label": label,
                "value": label,
            })

        return tuple(
            (
                school["id"],
                school["label"],
                school["value"],
            )
            for school in schools[:100]
        )

    raise GreenhouseEducationLookupError(
        "The school catalog could not be reached. Please try again."
    )


def search_greenhouse_schools(query, board_tokens=None):
    normalized_query = _normalize_query(query)
    normalized_tokens = _board_tokens(board_tokens)

    if not normalized_tokens:
        raise GreenhouseEducationLookupError(
            "No Greenhouse school catalog is available."
        )

    results = _cached_school_search(
        normalized_query.casefold(),
        normalized_tokens,
    )

    return [
        {
            "id": school_id,
            "label": label,
            "value": value,
        }
        for school_id, label, value in results
    ]
