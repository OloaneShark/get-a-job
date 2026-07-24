
import html
import re
from typing import Any

import requests


DEFAULT_TIMEOUT = 20

DEFAULT_HEADERS = {
    "User-Agent": (
        "JobAdInfinitum/1.0 "
        "(public job discovery; contact: admin)"
    ),
    "Accept": "*/*"
}


class JobSourceRequestError(RuntimeError):
    pass


def fetch_response(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT
) -> requests.Response:
    request_headers = DEFAULT_HEADERS.copy()

    if headers:
        request_headers.update(headers)

    try:
        response = requests.get(
            url,
            params=params,
            headers=request_headers,
            timeout=timeout
        )

        response.raise_for_status()
        return response

    except requests.Timeout as error:
        raise JobSourceRequestError(
            f"Request timed out while accessing {url}"
        ) from error

    except requests.RequestException as error:
        raise JobSourceRequestError(
            f"Request failed for {url}: {error}"
        ) from error


def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT
) -> Any:
    response = fetch_response(
        url,
        params=params,
        headers=headers,
        timeout=timeout
    )

    try:
        return response.json()

    except ValueError as error:
        raise JobSourceRequestError(
            f"Invalid JSON returned from {url}"
        ) from error


def fetch_html(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT
) -> str:
    response = fetch_response(
        url,
        params=params,
        headers=headers,
        timeout=timeout
    )

    return response.text


def clean_html_text(value: str | None) -> str | None:
    if not value:
        return None

    cleaned = html.unescape(value)

    cleaned = re.sub(
        r"<\s*br\s*/?\s*>",
        "\n",
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(
        r"</\s*(p|div|li|h[1-6]|section|article)\s*>",
        "\n",
        cleaned,
        flags=re.IGNORECASE
    )

    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)

    return cleaned.strip() or None

