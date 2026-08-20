
from functools import lru_cache


class LocationDataUnavailable(RuntimeError):
    pass


def _load_library():
    try:
        from country_state_city import (
            Country,
            State,
            City,
        )
    except ImportError as error:
        raise LocationDataUnavailable(
            "The country-state-city package is not installed."
        ) from error

    return Country, State, City


def _attribute(item, *names):
    for name in names:
        value = getattr(item, name, None)

        if value not in {None, ""}:
            return str(value)

    return ""


@lru_cache(maxsize=1)
def get_countries():
    Country, _, _ = _load_library()

    countries = []

    for country in Country.get_countries():
        name = _attribute(country, "name")
        code = _attribute(
            country,
            "iso_code",
            "iso2",
            "code",
        ).upper()

        if not name or not code:
            continue

        countries.append({
            "name": name,
            "code": code,
        })

    countries.sort(
        key=lambda item: item["name"].casefold()
    )

    return countries


@lru_cache(maxsize=512)
def get_states(country_code):
    _, State, _ = _load_library()

    country_code = str(
        country_code or ""
    ).strip().upper()

    if not country_code:
        return []

    states = []

    for state in State.get_states_of_country(country_code):
        name = _attribute(state, "name")
        code = _attribute(
            state,
            "iso_code",
            "state_code",
            "code",
        )

        if not name or not code:
            continue

        states.append({
            "name": name,
            "code": code,
        })

    states.sort(
        key=lambda item: item["name"].casefold()
    )

    return states


@lru_cache(maxsize=4096)
def get_cities(country_code, state_code):
    _, _, City = _load_library()

    country_code = str(
        country_code or ""
    ).strip().upper()
    state_code = str(
        state_code or ""
    ).strip()

    if not country_code or not state_code:
        return []

    cities = []
    seen = set()

    for city in City.get_cities_of_state(
        country_code,
        state_code,
    ):
        name = _attribute(city, "name").strip()
        normalized = name.casefold()

        if not name or normalized in seen:
            continue

        seen.add(normalized)

        cities.append({
            "name": name,
            "code": name,
        })

    cities.sort(
        key=lambda item: item["name"].casefold()
    )

    return cities
