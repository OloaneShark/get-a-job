
from urllib.parse import urlparse


GREENHOUSE_HOSTS = {
    "boards.greenhouse.io",
    "job-boards.greenhouse.io"
}


def extract_greenhouse_board_token(value):
    if not value or not value.strip():
        raise ValueError("A Greenhouse board URL or token is required.")

    cleaned_value = value.strip()

    if "://" not in cleaned_value:
        return cleaned_value.strip("/")

    parsed_url = urlparse(cleaned_value)
    hostname = (parsed_url.hostname or "").lower()

    if hostname not in GREENHOUSE_HOSTS:
        raise ValueError("This does not appear to be a Greenhouse job-board URL.")

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if not path_parts:
        raise ValueError("The Greenhouse board URL does not contain a company token.")

    return path_parts[0]
