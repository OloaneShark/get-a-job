
from urllib.parse import urlparse


GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io"
}

LEVER_HOSTS = {
    "jobs.lever.co"
}

ASHBY_HOSTS = {
    "jobs.ashbyhq.com"
}


def extract_greenhouse_board_token(value):
    if not value or not value.strip():
        raise ValueError(
            "A Greenhouse board URL or token is required."
        )

    cleaned_value = value.strip()

    if "://" not in cleaned_value:
        return cleaned_value.strip("/")

    parsed_url = urlparse(cleaned_value)
    hostname = (parsed_url.hostname or "").lower()

    if hostname not in GREENHOUSE_HOSTS:
        raise ValueError(
            "This does not appear to be a Greenhouse job-board URL."
        )

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if not path_parts:
        raise ValueError(
            "The Greenhouse board URL does not contain a company token."
        )

    return path_parts[0]


def extract_lever_company_slug(value):
    if not value or not value.strip():
        raise ValueError(
            "A Lever careers URL or company slug is required."
        )

    cleaned_value = value.strip()

    if "://" not in cleaned_value:
        return cleaned_value.strip("/")

    parsed_url = urlparse(cleaned_value)
    hostname = (parsed_url.hostname or "").lower()

    if hostname not in LEVER_HOSTS:
        raise ValueError(
            "This does not appear to be a Lever careers URL."
        )

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if not path_parts:
        raise ValueError(
            "The Lever careers URL does not contain a company slug."
        )

    return path_parts[0]


def extract_ashby_job_board_name(value):
    if not value or not value.strip():
        raise ValueError(
            "An Ashby careers URL or job-board name is required."
        )

    cleaned_value = value.strip()

    if "://" not in cleaned_value:
        return cleaned_value.strip("/")

    parsed_url = urlparse(cleaned_value)
    hostname = (parsed_url.hostname or "").lower()

    if hostname not in ASHBY_HOSTS:
        raise ValueError(
            "This does not appear to be an Ashby careers URL."
        )

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if not path_parts:
        raise ValueError(
            "The Ashby careers URL does not contain a job-board name."
        )

    return path_parts[0]


