
from functools import lru_cache

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

from services.location_service import get_countries


@lru_cache(maxsize=1)
def get_phone_country_choices():
    names = {
        item["code"].upper(): item["name"]
        for item in get_countries()
    }

    choices = []

    for region in phonenumbers.SUPPORTED_REGIONS:
        dial = phonenumbers.country_code_for_region(region)
        if not dial:
            continue

        choices.append(
            (
                region,
                f"{names.get(region, region)} (+{dial})",
            )
        )

    return sorted(
        choices,
        key=lambda item: item[1].casefold(),
    )


def country_region_from_name(country_name):
    value = str(country_name or "").strip().casefold()

    for item in get_countries():
        if item["name"].strip().casefold() == value:
            return item["code"].upper()

    return ""


def split_phone_for_form(value, preferred_region=None):
    raw = str(value or "").strip()
    region = str(preferred_region or "").strip().upper() or None

    if not raw:
        return region or "", ""

    try:
        parsed = phonenumbers.parse(
            raw,
            None if raw.startswith("+") else region,
        )
    except NumberParseException:
        return region or "", raw

    return (
        phonenumbers.region_code_for_number(parsed)
        or region
        or "",
        phonenumbers.national_significant_number(parsed),
    )


def normalize_phone_number(value, region_code):
    raw = str(value or "").strip()

    if not raw:
        return None

    region = str(region_code or "").strip().upper()

    if not region:
        raise ValueError(
            "Choose the country for this phone number."
        )

    try:
        parsed = phonenumbers.parse(
            raw,
            None if raw.startswith("+") else region,
        )
    except NumberParseException as error:
        raise ValueError(
            "Enter a valid phone number for the selected country."
        ) from error

    detected = phonenumbers.region_code_for_number(parsed)

    if detected and detected != region:
        raise ValueError(
            "The phone number country code does not match "
            "the selected phone country."
        )

    if not phonenumbers.is_possible_number(parsed):
        raise ValueError(
            "That phone number is not possible for the selected country."
        )

    if not phonenumbers.is_valid_number(parsed):
        raise ValueError(
            "Enter a valid phone number for the selected country."
        )

    return phonenumbers.format_number(
        parsed,
        PhoneNumberFormat.E164,
    )
