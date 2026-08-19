
import json
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_html
from services.job_sources.job_match_service import (
    job_matches_profile,
    matches_role_title,
)


class AppleJobsSource(BaseJobSource):
    source_name = "Apple Jobs"
    source_type = "apple_jobs"
    requires_company_config = False

    base_url = "https://jobs.apple.com"
    search_url = "https://jobs.apple.com/en-us/search"

    page_size = 20
    max_pages_per_team = 100
    listing_workers = 4
    detail_workers = 6
    cache_duration = timedelta(hours=6)

    # Apple first-party team filters that are technology-focused.
    # The shared profile matcher still decides which roles matter to
    # each individual user.
    tech_teams = (
        (
            "Software and Services: Apps and Frameworks",
            "apps-and-frameworks-SFTWR-AF",
            "Apps and Frameworks",
        ),
        (
            "Software and Services: Cloud and Infrastructure",
            "cloud-and-infrastructure-SFTWR-CLD",
            "Cloud and Infrastructure",
        ),
        (
            "Software and Services: Core Operating Systems",
            "core-operating-systems-SFTWR-COS",
            "Core Operating Systems",
        ),
        (
            "Software and Services: Information Systems and Technology",
            "information-systems-technology-SFTWR-ISTECH",
            "Information Systems and Technology",
        ),
        (
            "Software and Services: Machine Learning and AI",
            "machine-learning-and-ai-SFTWR-MCHLN",
            "Machine Learning and AI",
        ),
        (
            "Software and Services: Security and Privacy",
            "security-and-privacy-SFTWR-SEC",
            "Security and Privacy",
        ),
        (
            "Software and Services: Software Quality, Automation, and Tools",
            "software-quality-automation-and-tools-SFTWR-SQAT",
            "Software Quality",
        ),
        (
            "Software and Services: Wireless Software",
            "wireless-software-SFTWR-WSFT",
            "Wireless Software",
        ),
        (
            "Hardware: Acoustic Technologies",
            "acoustic-technologies-HRDWR-ACT",
            "Acoustic Technologies",
        ),
        (
            "Hardware: Architecture",
            "architecture-HRDWR-ARCH",
            "Architecture",
        ),
        (
            "Hardware: Battery Engineering",
            "battery-engineering-HRDWR-BE",
            "Battery Engineering",
        ),
        (
            "Hardware: Camera Technologies",
            "camera-technologies-HRDWR-CAM",
            "Camera Technologies",
        ),
        (
            "Hardware: Display Technologies",
            "display-technologies-HRDWR-DISP",
            "Display Technologies",
        ),
        (
            "Hardware: Engineering Project Management",
            "engineering-project-management-HRDWR-EPM",
            "Engineering Project Management",
        ),
        (
            "Hardware: Mechanical Engineering",
            "mechanical-engineering-HRDWR-ME",
            "Mechanical Engineering",
        ),
        (
            "Hardware: Reliability Engineering",
            "reliability-engineering-HRDWR-REL",
            "Reliability Engineering",
        ),
        (
            "Hardware: Sensor Technologies",
            "sensor-technologies-HRDWR-SENT",
            "Sensor Technologies",
        ),
        (
            "Hardware: Silicon Technologies",
            "silicon-technologies-HRDWR-SILT",
            "Silicon Technologies",
        ),
        (
            "Hardware: System Design and Test Engineering",
            "system-design-and-test-engineering-HRDWR-SDE",
            "System Design and Test Engineering",
        ),
        (
            "Hardware: Wireless Hardware",
            "wireless-hardware-HRDWR-WT",
            "Wireless Hardware",
        ),
    )

    _cache_lock = threading.Lock()
    _cached_jobs = None
    _cache_fetched_at = None
    _cached_stats = None
    _cached_signature = None

    _detail_cache = {}

    hydration_pattern = re.compile(
        r'window\.__staticRouterHydrationData\s*=\s*'
        r'JSON\.parse\('
        r'(?P<literal>"(?:\\.|[^"\\])*")'
        r'\)',
        flags=re.DOTALL,
    )

    detail_role_pattern = re.compile(
        r"/details/([^/?#]+)",
        flags=re.IGNORECASE,
    )

    posted_date_pattern = re.compile(
        r"\b("
        r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
        r")\s+(\d{1,2}),\s+(\d{4})\b",
        flags=re.IGNORECASE,
    )

    salary_range_patterns = (
        re.compile(
            r"\bbase pay range\b.*?\bbetween\s+"
            r"(\$[\d,]+(?:\.\d+)?)\s+and\s+"
            r"(\$[\d,]+(?:\.\d+)?)",
            flags=re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"\bpay range\b.*?"
            r"(\$[\d,]+(?:\.\d+)?)\s*(?:-|to|and)\s*"
            r"(\$[\d,]+(?:\.\d+)?)",
            flags=re.IGNORECASE | re.DOTALL,
        ),
    )

    @staticmethod
    def normalize_text(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @classmethod
    def cache_is_fresh(cls):
        return (
            cls._cached_jobs is not None
            and cls._cache_fetched_at is not None
            and (
                datetime.now(timezone.utc)
                - cls._cache_fetched_at
            ) < cls.cache_duration
        )

    @classmethod
    def profile_signature(cls, profiles):
        signature = []

        for profile in profiles:
            keywords = cls.normalize_text(
                getattr(profile, "keywords", "")
            ).casefold()

            max_age = getattr(
                profile,
                "maximum_posting_age_days",
                395,
            )

            try:
                max_age = int(max_age)
            except (TypeError, ValueError):
                max_age = 395

            signature.append(
                (
                    keywords,
                    max(0, max_age),
                )
            )

        return tuple(sorted(signature))

    @classmethod
    def maximum_requested_age_days(cls, profiles):
        values = []

        for profile in profiles:
            value = getattr(
                profile,
                "maximum_posting_age_days",
                395,
            )

            try:
                value = int(value)
            except (TypeError, ValueError):
                value = 395

            values.append(
                max(0, value)
            )

        return max(values) if values else 395

    @classmethod
    def parse_date(cls, value):
        text = cls.normalize_text(value)

        if not text:
            return None

        for format_string in (
            "%b %d, %Y",
            "%B %d, %Y",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(
                    text,
                    format_string,
                )
            except ValueError:
                continue

            return parsed.replace(
                tzinfo=timezone.utc
            )

        return None

    @classmethod
    def parse_reported_count(cls, text):
        normalized = cls.normalize_text(text)

        match = re.search(
            r"\b(\d[\d,]*)\+?\s*Result",
            normalized,
            flags=re.IGNORECASE,
        )

        if not match:
            return None, False

        try:
            count = int(
                match.group(1).replace(",", "")
            )
        except ValueError:
            return None, False

        capped = "+" in match.group(0)

        return count, capped

    @classmethod
    def extract_role_number(cls, url):
        match = cls.detail_role_pattern.search(
            str(url or "")
        )

        if not match:
            return None

        value = cls.normalize_text(
            match.group(1)
        )

        return value or None

    @classmethod
    def find_result_card(cls, anchor):
        node = anchor
        best = None

        for _ in range(10):
            node = getattr(
                node,
                "parent",
                None,
            )

            if node is None:
                break

            text = cls.normalize_text(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if not text:
                continue

            if len(text) > 12000:
                break

            if (
                "Role Number" in text
                and "Location" in text
            ):
                best = node

                if (
                    "Weekly Hours" in text
                    or "Submit Resume" in text
                ):
                    break

        return best or anchor.parent or anchor

    @classmethod
    def listing_title(cls, card, anchor):
        for tag_name in (
            "h2",
            "h3",
            "h4",
        ):
            heading = card.find(
                tag_name
            )

            if heading:
                text = cls.normalize_text(
                    heading.get_text(
                        " ",
                        strip=True,
                    )
                )

                if text:
                    return text

        anchor_text = cls.normalize_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        ignored = {
            "see full role description",
            "submit resume",
            "actions",
        }

        if (
            anchor_text
            and anchor_text.casefold()
            not in ignored
        ):
            return anchor_text

        return None

    @classmethod
    def listing_location(cls, card_text):
        match = re.search(
            r"\bLocation\s+(.+?)\s+Actions\b",
            card_text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        return cls.normalize_text(
            match.group(1)
        ) or None

    @classmethod
    def listing_weekly_hours(cls, card_text):
        match = re.search(
            r"\bWeekly Hours:\s*"
            r"([0-9]+(?:\.[0-9]+)?)"
            r"(?:\s*Hours?)?",
            card_text,
            flags=re.IGNORECASE,
        )

        if not match:
            return None

        try:
            return float(
                match.group(1)
            )
        except ValueError:
            return None

    @classmethod
    def listing_posted_at(cls, card_text):
        match = cls.posted_date_pattern.search(
            card_text
        )

        if not match:
            return None

        return cls.parse_date(
            match.group(0)
        )

    @classmethod
    def listing_snippet(cls, card_text):
        patterns = (
            re.compile(
                r"\bWeekly Hours:\s*"
                r"[0-9]+(?:\.[0-9]+)?"
                r"(?:\s*Hours?)?\s+"
                r"(.+?)\s+Submit Resume\b",
                flags=re.IGNORECASE | re.DOTALL,
            ),
            re.compile(
                r"\bRole Number:\s*"
                r"[A-Za-z0-9-]+\s+"
                r"(.+?)\s+Submit Resume\b",
                flags=re.IGNORECASE | re.DOTALL,
            ),
        )

        for pattern in patterns:
            match = pattern.search(
                card_text
            )

            if not match:
                continue

            text = cls.normalize_text(
                match.group(1)
            )

            if text:
                return text

        return None

    @classmethod
    def normalize_listing_job(
        cls,
        *,
        role_number,
        title,
        url,
        card_text,
        team_label,
    ):
        if (
            not role_number
            or not title
            or not url
        ):
            return None

        posted_at = cls.listing_posted_at(
            card_text
        )
        location = cls.listing_location(
            card_text
        )
        weekly_hours = (
            cls.listing_weekly_hours(
                card_text
            )
        )
        snippet = cls.listing_snippet(
            card_text
        )

        title_text = title.casefold()

        if "intern" in title_text:
            employment_type = "Internship"
            experience_level = "intern"
        elif (
            "early career" in title_text
            or "new grad" in title_text
            or "new graduate" in title_text
        ):
            employment_type = (
                "Full-time"
                if weekly_hours is None
                or weekly_hours >= 30
                else "Part-time"
            )
            experience_level = "entry"
        else:
            if weekly_hours is None:
                employment_type = None
            elif weekly_hours >= 30:
                employment_type = "Full-time"
            elif weekly_hours > 0:
                employment_type = "Part-time"
            else:
                employment_type = None

            if re.search(
                r"\bjunior\b|\bjr\.?\b",
                title_text,
            ):
                experience_level = "junior"
            elif (
                "manager" in title_text
                or "director" in title_text
            ):
                experience_level = "manager"
            else:
                experience_level = None

        return {
            "source": cls.source_name,
            "external_id": role_number,
            "company_name": "Apple",
            "position_title": title,
            "location": location or "Unknown",
            "location_source": (
                "apple_search_card"
                if location
                else "unknown"
            ),
            "location_confidence": (
                1.0
                if location
                else 0.0
            ),
            "employment_type": employment_type,
            "salary": None,
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": "Unknown",
            "posting_url": url,
            "apply_url": url,
            "job_description": snippet,
            "departments": [team_label],
            "offices": [location] if location else [],
            "is_remote": False,
            "workplace_type": "On-site",
            "remote_candidate_scope": None,
            "remote_allowed_locations": [],
            "published_at": posted_at,
            "experience_level": experience_level,
            "seniority_level": experience_level,
            "weekly_hours": weekly_hours,
            "source_listing_url": cls.search_url,
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def parse_search_page(
        cls,
        html,
        team_label,
    ):
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        page_text = cls.normalize_text(
            soup.get_text(
                " ",
                strip=True,
            )
        )

        reported_count, capped = (
            cls.parse_reported_count(
                page_text
            )
        )

        listings = []
        seen = set()

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            href = cls.normalize_text(
                anchor.get("href")
            )

            if "/details/" not in href:
                continue

            url = urljoin(
                cls.base_url,
                href,
            )

            role_number = (
                cls.extract_role_number(
                    url
                )
            )

            if (
                not role_number
                or role_number in seen
            ):
                continue

            card = cls.find_result_card(
                anchor
            )
            card_text = cls.normalize_text(
                card.get_text(
                    " ",
                    strip=True,
                )
            )

            title = cls.listing_title(
                card,
                anchor,
            )

            normalized = (
                cls.normalize_listing_job(
                    role_number=role_number,
                    title=title,
                    url=url,
                    card_text=card_text,
                    team_label=team_label,
                )
            )

            if normalized is None:
                continue

            seen.add(role_number)
            listings.append(
                normalized
            )

        return {
            "listings": listings,
            "reported_count": reported_count,
            "reported_capped": capped,
            "page_text": page_text,
        }

    @classmethod
    def listing_within_age(
        cls,
        job,
        max_age_days,
    ):
        published_at = job.get(
            "published_at"
        )

        if not isinstance(
            published_at,
            datetime,
        ):
            return True

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(
                days=max_age_days,
            )
        )

        return published_at >= cutoff

    @classmethod
    def page_is_entirely_too_old(
        cls,
        jobs,
        max_age_days,
    ):
        dated = [
            job.get("published_at")
            for job in jobs
            if isinstance(
                job.get("published_at"),
                datetime,
            )
        ]

        if not dated:
            return False

        cutoff = (
            datetime.now(timezone.utc)
            - timedelta(
                days=max_age_days,
            )
        )

        return max(dated) < cutoff

    @classmethod
    def fetch_team_listings(
        cls,
        team_label,
        team_slug,
        guard_text,
        max_age_days,
    ):
        collected = []
        seen = set()
        requests_used = 0
        reported_count = None
        reported_capped = False
        page_limit = cls.max_pages_per_team

        for page in range(
            1,
            cls.max_pages_per_team + 1,
        ):
            html = fetch_html(
                cls.search_url,
                params={
                    "team": team_slug,
                    "page": page,
                },
                timeout=45,
            )
            requests_used += 1

            parsed = cls.parse_search_page(
                html,
                team_label,
            )

            if page == 1:
                page_text = (
                    parsed["page_text"]
                    .casefold()
                )

                if (
                    guard_text.casefold()
                    not in page_text
                ):
                    raise RuntimeError(
                        "Apple appears to have ignored "
                        f"team filter '{team_slug}'. "
                        f"Expected page text to contain "
                        f"'{guard_text}'."
                    )

                reported_count = (
                    parsed[
                        "reported_count"
                    ]
                )
                reported_capped = (
                    parsed[
                        "reported_capped"
                    ]
                )

                if (
                    reported_count is not None
                    and not reported_capped
                ):
                    page_limit = min(
                        cls.max_pages_per_team,
                        max(
                            1,
                            math.ceil(
                                reported_count
                                / cls.page_size
                            ),
                        ),
                    )

            page_jobs = parsed[
                "listings"
            ]

            if not page_jobs:
                break

            new_jobs = []

            for job in page_jobs:
                role_number = job[
                    "external_id"
                ]

                if role_number in seen:
                    continue

                seen.add(role_number)

                if cls.listing_within_age(
                    job,
                    max_age_days,
                ):
                    collected.append(
                        job
                    )
                    new_jobs.append(
                        job
                    )

            if not new_jobs and page > 1:
                # Repeated/old territory. If every dated
                # job on the page is older than the largest
                # active profile window, there is no reason
                # to continue a newest-first listing.
                if cls.page_is_entirely_too_old(
                    page_jobs,
                    max_age_days,
                ):
                    break

                page_ids = {
                    job["external_id"]
                    for job in page_jobs
                }

                if page_ids <= seen:
                    break

            if cls.page_is_entirely_too_old(
                page_jobs,
                max_age_days,
            ):
                break

            if page >= page_limit:
                break

            if (
                not reported_capped
                and len(page_jobs)
                < cls.page_size
            ):
                break

        print(
            "APPLE JOBS TEAM | "
            f"Team: {team_label} | "
            f"Reported: "
            f"{str(reported_count) + '+' if reported_capped else reported_count} | "
            f"Listings kept: {len(collected)} | "
            f"Requests: {requests_used}"
        )

        return {
            "label": team_label,
            "slug": team_slug,
            "reported_count": (
                reported_count
            ),
            "reported_capped": (
                reported_capped
            ),
            "listings": collected,
            "requests": requests_used,
        }

    @classmethod
    def recursive_values(
        cls,
        value,
        key,
    ):
        found = []

        def visit(item):
            if isinstance(item, dict):
                for item_key, item_value in (
                    item.items()
                ):
                    if item_key == key:
                        found.append(
                            item_value
                        )

                    visit(
                        item_value
                    )

            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(value)

        return found

    @classmethod
    def find_job_data(cls, hydration):
        best = None
        best_score = -1

        wanted_keys = {
            "postingTitle",
            "jobSummary",
            "description",
            "responsibilities",
            "minimumQualifications",
            "preferredQualifications",
            "educationAndExperience",
            "additionalRequirements",
        }

        def visit(item):
            nonlocal best
            nonlocal best_score

            if isinstance(item, dict):
                score = len(
                    wanted_keys
                    & set(item.keys())
                )

                if (
                    "postingTitle" in item
                    and score > best_score
                ):
                    best = item
                    best_score = score

                for child in item.values():
                    visit(child)

            elif isinstance(item, list):
                for child in item:
                    visit(child)

        visit(hydration)

        return best

    @classmethod
    def parse_hydration(cls, html):
        match = cls.hydration_pattern.search(
            html
        )

        if not match:
            raise RuntimeError(
                "Apple detail page did not contain "
                "__staticRouterHydrationData."
            )

        literal = match.group(
            "literal"
        )

        try:
            serialized = json.loads(
                literal
            )
            hydration = json.loads(
                serialized
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise RuntimeError(
                "Apple detail hydration JSON "
                "could not be decoded."
            ) from error

        if not isinstance(
            hydration,
            dict,
        ):
            raise RuntimeError(
                "Apple detail hydration data "
                "had an unexpected shape."
            )

        return hydration

    @classmethod
    def first_recursive_value(
        cls,
        hydration,
        key,
        predicate=None,
    ):
        for value in cls.recursive_values(
            hydration,
            key,
        ):
            if (
                predicate is None
                or predicate(value)
            ):
                return value

        return None

    @classmethod
    def normalize_location_dict(
        cls,
        value,
    ):
        if not isinstance(
            value,
            dict,
        ):
            return None

        city = cls.normalize_text(
            value.get("city")
            or value.get("name")
        )
        state = cls.normalize_text(
            value.get(
                "stateProvince"
            )
            or value.get("region")
        )
        country = cls.normalize_text(
            value.get("countryName")
        )

        parts = []

        for item in (
            city,
            state,
            country,
        ):
            if (
                item
                and item.casefold()
                not in {
                    existing.casefold()
                    for existing in parts
                }
            ):
                parts.append(item)

        if not parts:
            return None

        return ", ".join(parts)

    @classmethod
    def hydration_locations(
        cls,
        hydration,
        listing_job,
    ):
        locations = []

        def add(value):
            text = cls.normalize_text(
                value
            )

            if not text:
                return

            key = text.casefold()

            if key in {
                existing.casefold()
                for existing in locations
            }:
                return

            locations.append(text)

        selected = (
            cls.first_recursive_value(
                hydration,
                "selectedLocation",
                lambda value: isinstance(
                    value,
                    dict,
                ),
            )
        )

        if selected:
            add(
                cls.normalize_location_dict(
                    selected
                )
            )

        for key in (
            "location",
            "localeLocation",
        ):
            values = cls.recursive_values(
                hydration,
                key,
            )

            for value in values:
                if isinstance(
                    value,
                    list,
                ):
                    for item in value:
                        add(
                            cls.normalize_location_dict(
                                item
                            )
                            if isinstance(
                                item,
                                dict,
                            )
                            else item
                        )

                elif isinstance(
                    value,
                    dict,
                ):
                    add(
                        cls.normalize_location_dict(
                            value
                        )
                    )

        if not locations:
            add(
                listing_job.get(
                    "location"
                )
            )

        return [
            location
            for location
            in locations
            if location.casefold()
            != "unknown"
        ]

    @classmethod
    def hydration_teams(
        cls,
        hydration,
        listing_job,
    ):
        teams = []

        for value in cls.recursive_values(
            hydration,
            "teams",
        ):
            if not isinstance(
                value,
                list,
            ):
                continue

            for item in value:
                if isinstance(
                    item,
                    dict,
                ):
                    text = cls.normalize_text(
                        item.get("name")
                        or item.get("code")
                    )
                else:
                    text = cls.normalize_text(
                        item
                    )

                if (
                    text
                    and text.casefold()
                    not in {
                        existing.casefold()
                        for existing in teams
                    }
                ):
                    teams.append(text)

        for value in (
            listing_job.get(
                "departments"
            )
            or []
        ):
            text = cls.normalize_text(
                value
            )

            if (
                text
                and text.casefold()
                not in {
                    existing.casefold()
                    for existing in teams
                }
            ):
                teams.append(text)

        return teams

    @classmethod
    def combined_description(
        cls,
        job_data,
    ):
        sections = (
            (
                "Summary",
                job_data.get(
                    "jobSummary"
                ),
            ),
            (
                "Description",
                job_data.get(
                    "description"
                ),
            ),
            (
                "Responsibilities",
                job_data.get(
                    "responsibilities"
                ),
            ),
            (
                "Minimum Qualifications",
                job_data.get(
                    "minimumQualifications"
                ),
            ),
            (
                "Preferred Qualifications",
                job_data.get(
                    "preferredQualifications"
                ),
            ),
            (
                "Education & Experience",
                job_data.get(
                    "educationAndExperience"
                ),
            ),
            (
                "Additional Requirements",
                job_data.get(
                    "additionalRequirements"
                ),
            ),
        )

        output = []
        seen = set()

        for label, raw_value in sections:
            text = clean_html_text(
                raw_value
            )

            if not text:
                continue

            key = text.casefold()

            if key in seen:
                continue

            seen.add(key)
            output.append(
                f"{label}:\n{text}"
            )

        return (
            "\n\n".join(output)
            or None
        )

    @classmethod
    def salary_from_hydration(
        cls,
        hydration,
    ):
        contents = []

        for footers in cls.recursive_values(
            hydration,
            "postingFooters",
        ):
            if not isinstance(
                footers,
                list,
            ):
                continue

            for footer in footers:
                if not isinstance(
                    footer,
                    dict,
                ):
                    continue

                localizations = footer.get(
                    "localizations"
                )

                if not isinstance(
                    localizations,
                    dict,
                ):
                    continue

                for entries in (
                    localizations.values()
                ):
                    if not isinstance(
                        entries,
                        list,
                    ):
                        continue

                    for entry in entries:
                        if not isinstance(
                            entry,
                            dict,
                        ):
                            continue

                        name = cls.normalize_text(
                            entry.get(
                                "name"
                            )
                        )

                        if (
                            "pay" not in name.casefold()
                            and "compensation"
                            not in name.casefold()
                        ):
                            continue

                        text = clean_html_text(
                            entry.get(
                                "content"
                            )
                        )

                        if text:
                            contents.append(
                                text
                            )

        for content in contents:
            for pattern in (
                cls.salary_range_patterns
            ):
                match = pattern.search(
                    content
                )

                if match:
                    return (
                        f"{match.group(1)} - "
                        f"{match.group(2)}"
                    )

        return None

    @classmethod
    def workplace_metadata(
        cls,
        hydration,
        description,
        locations,
    ):
        home_office = (
            cls.first_recursive_value(
                hydration,
                "homeOffice",
                lambda value: isinstance(
                    value,
                    bool,
                ),
            )
        )

        searchable = cls.normalize_text(
            description
        ).casefold()

        if home_office is True:
            workplace_type = "Remote"
        elif re.search(
            r"\bhybrid "
            r"(?:role|position|schedule|work)\b"
            r"|\bhybrid work model\b",
            searchable,
        ):
            workplace_type = "Hybrid"
        elif re.search(
            r"\bfully remote\b"
            r"|\bremote[- ]first\b"
            r"|\bthis is (?:a )?remote "
            r"(?:role|position)\b"
            r"|\bwork from home\b",
            searchable,
        ):
            workplace_type = "Remote"
        else:
            workplace_type = "On-site"

        if workplace_type == "Remote":
            if locations:
                return {
                    "workplace_type": "Remote",
                    "is_remote": True,
                    "location": (
                        "Remote | "
                        + " | ".join(
                            locations
                        )
                    ),
                    "location_source": (
                        "apple_hydration_remote_location"
                    ),
                    "location_confidence": 0.9,
                    "remote_candidate_scope": (
                        "selected_locations"
                    ),
                    "remote_allowed_locations": (
                        list(locations)
                    ),
                }

            return {
                "workplace_type": "Remote",
                "is_remote": True,
                "location": "Remote",
                "location_source": (
                    "apple_hydration_remote_unspecified"
                ),
                "location_confidence": 0.4,
                "remote_candidate_scope": None,
                "remote_allowed_locations": [],
            }

        location = (
            " | ".join(
                locations
            )
            if locations
            else "Unknown"
        )

        return {
            "workplace_type": (
                workplace_type
            ),
            "is_remote": (
                workplace_type
                == "Hybrid"
            ),
            "location": location,
            "location_source": (
                "apple_hydration_location"
                if locations
                else "unknown"
            ),
            "location_confidence": (
                1.0
                if locations
                else 0.0
            ),
            "remote_candidate_scope": None,
            "remote_allowed_locations": [],
        }

    @classmethod
    def normalize_detail_job(
        cls,
        hydration,
        listing_job,
    ):
        job_data = cls.find_job_data(
            hydration
        )

        if not isinstance(
            job_data,
            dict,
        ):
            raise RuntimeError(
                "Apple hydration data did not "
                "contain a recognizable job object."
            )

        title = (
            cls.normalize_text(
                job_data.get(
                    "postingTitle"
                )
            )
            or listing_job[
                "position_title"
            ]
        )

        description = (
            cls.combined_description(
                job_data
            )
            or listing_job.get(
                "job_description"
            )
        )

        locations = (
            cls.hydration_locations(
                hydration,
                listing_job,
            )
        )

        workplace = (
            cls.workplace_metadata(
                hydration,
                description,
                locations,
            )
        )

        posting_date = (
            cls.first_recursive_value(
                hydration,
                "postingDate",
                lambda value: isinstance(
                    value,
                    str,
                ),
            )
        )

        published_at = (
            cls.parse_date(
                posting_date
            )
            or listing_job.get(
                "published_at"
            )
        )

        standard_hours = (
            cls.first_recursive_value(
                hydration,
                "standardWeeklyHours",
                lambda value: isinstance(
                    value,
                    (int, float, str),
                ),
            )
        )

        try:
            standard_hours = float(
                standard_hours
            )
        except (
            TypeError,
            ValueError,
        ):
            standard_hours = (
                listing_job.get(
                    "weekly_hours"
                )
            )

        title_text = title.casefold()

        if "intern" in title_text:
            employment_type = "Internship"
            experience_level = "intern"
        else:
            if (
                standard_hours
                is not None
                and standard_hours > 0
            ):
                employment_type = (
                    "Full-time"
                    if standard_hours >= 30
                    else "Part-time"
                )
            else:
                employment_type = (
                    listing_job.get(
                        "employment_type"
                    )
                )

            if (
                "early career"
                in title_text
                or "new grad"
                in title_text
                or "new graduate"
                in title_text
            ):
                experience_level = "entry"
            elif re.search(
                r"\bjunior\b|\bjr\.?\b",
                title_text,
            ):
                experience_level = "junior"
            elif (
                "manager" in title_text
                or "director" in title_text
            ):
                experience_level = "manager"
            else:
                experience_level = None

        teams = cls.hydration_teams(
            hydration,
            listing_job,
        )

        return {
            "source": cls.source_name,
            "external_id": (
                listing_job[
                    "external_id"
                ]
            ),
            "company_name": "Apple",
            "position_title": title,
            "location": workplace[
                "location"
            ],
            "location_source": (
                workplace[
                    "location_source"
                ]
            ),
            "location_confidence": (
                workplace[
                    "location_confidence"
                ]
            ),
            "employment_type": (
                employment_type
            ),
            "salary": (
                cls.salary_from_hydration(
                    hydration
                )
            ),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": (
                listing_job[
                    "posting_url"
                ]
            ),
            "apply_url": (
                listing_job[
                    "posting_url"
                ]
            ),
            "job_description": description,
            "departments": teams,
            "offices": locations,
            "is_remote": workplace[
                "is_remote"
            ],
            "workplace_type": (
                workplace[
                    "workplace_type"
                ]
            ),
            "remote_candidate_scope": (
                workplace[
                    "remote_candidate_scope"
                ]
            ),
            "remote_allowed_locations": (
                workplace[
                    "remote_allowed_locations"
                ]
            ),
            "published_at": published_at,
            "experience_level": (
                experience_level
            ),
            "seniority_level": (
                experience_level
            ),
            "weekly_hours": standard_hours,
            "source_listing_url": (
                listing_job.get(
                    "source_listing_url"
                )
                or cls.search_url
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def detail_cache_get(
        cls,
        role_number,
    ):
        with cls._cache_lock:
            item = cls._detail_cache.get(
                role_number
            )

            if not item:
                return None

            fetched_at = item[
                "fetched_at"
            ]

            if (
                datetime.now(
                    timezone.utc
                )
                - fetched_at
            ) >= cls.cache_duration:
                cls._detail_cache.pop(
                    role_number,
                    None,
                )
                return None

            return item["job"]

    @classmethod
    def detail_cache_set(
        cls,
        role_number,
        job,
    ):
        with cls._cache_lock:
            cls._detail_cache[
                role_number
            ] = {
                "fetched_at": (
                    datetime.now(
                        timezone.utc
                    )
                ),
                "job": job,
            }

        return job

    @classmethod
    def fetch_detail_job(
        cls,
        listing_job,
    ):
        role_number = listing_job[
            "external_id"
        ]

        cached = cls.detail_cache_get(
            role_number
        )

        if cached is not None:
            return cached, True

        html = fetch_html(
            listing_job[
                "posting_url"
            ],
            timeout=45,
        )

        hydration = cls.parse_hydration(
            html
        )

        job = cls.normalize_detail_job(
            hydration,
            listing_job,
        )

        return (
            cls.detail_cache_set(
                role_number,
                job,
            ),
            False,
        )

    @classmethod
    def any_profile_role_match(
        cls,
        job,
        profiles,
    ):
        return any(
            matches_role_title(
                job,
                profile,
            )
            for profile in profiles
        )

    @classmethod
    def prepare_jobs(
        cls,
        profiles,
    ):
        max_age_days = (
            cls.maximum_requested_age_days(
                profiles
            )
        )

        team_results = []
        team_errors = {}

        with ThreadPoolExecutor(
            max_workers=cls.listing_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.fetch_team_listings,
                    label,
                    slug,
                    guard_text,
                    max_age_days,
                ): (
                    label,
                    slug,
                )
                for (
                    label,
                    slug,
                    guard_text,
                )
                in cls.tech_teams
            }

            for future in as_completed(
                future_map
            ):
                label, slug = (
                    future_map[future]
                )

                try:
                    result = future.result()
                except Exception as error:
                    team_errors[
                        slug
                    ] = str(error)

                    print(
                        "APPLE JOBS TEAM FAILED | "
                        f"Team: {label} | "
                        f"Error: {error}"
                    )
                    continue

                team_results.append(
                    result
                )

        if (
            not team_results
            and team_errors
        ):
            raise RuntimeError(
                "Apple Jobs failed for every "
                "technology team."
            )

        raw_listing_count = sum(
            len(
                result["listings"]
            )
            for result
            in team_results
        )

        listing_requests = sum(
            result["requests"]
            for result
            in team_results
        )

        deduplicated = {}

        for result in team_results:
            listing_url = (
                f"{cls.search_url}"
                f"?team={result['slug']}"
            )

            for job in result[
                "listings"
            ]:
                role_number = job[
                    "external_id"
                ]

                existing = (
                    deduplicated.get(
                        role_number
                    )
                )

                if existing is None:
                    copy = dict(job)
                    copy[
                        "source_listing_url"
                    ] = listing_url
                    deduplicated[
                        role_number
                    ] = copy
                    continue

                departments = list(
                    existing.get(
                        "departments"
                    )
                    or []
                )

                for department in (
                    job.get(
                        "departments"
                    )
                    or []
                ):
                    if (
                        department
                        and department.casefold()
                        not in {
                            item.casefold()
                            for item in departments
                        }
                    ):
                        departments.append(
                            department
                        )

                existing[
                    "departments"
                ] = departments

                if (
                    not existing.get(
                        "job_description"
                    )
                    and job.get(
                        "job_description"
                    )
                ):
                    existing[
                        "job_description"
                    ] = job[
                        "job_description"
                    ]

        listings = list(
            deduplicated.values()
        )

        role_candidates = [
            job
            for job in listings
            if cls.any_profile_role_match(
                job,
                profiles,
            )
        ]

        print(
            "APPLE JOBS PRE-DETAIL FILTER | "
            f"Profiles: {len(profiles)} | "
            f"Raw listings: {raw_listing_count} | "
            f"Unique listings: {len(listings)} | "
            f"Role candidates: {len(role_candidates)}"
        )

        normalized = []
        detail_errors = 0
        detail_cache_hits = 0

        with ThreadPoolExecutor(
            max_workers=cls.detail_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.fetch_detail_job,
                    listing_job,
                ): listing_job
                for listing_job
                in role_candidates
            }

            for future in as_completed(
                future_map
            ):
                listing_job = (
                    future_map[future]
                )

                try:
                    job, cache_hit = (
                        future.result()
                    )
                except Exception as error:
                    detail_errors += 1

                    print(
                        "APPLE JOBS DETAIL FAILED | "
                        f"Role: "
                        f"{listing_job['external_id']} | "
                        f"Error: {error}"
                    )

                    # Search cards still contain a useful
                    # title/location/date/snippet fallback.
                    normalized.append(
                        listing_job
                    )
                    continue

                if cache_hit:
                    detail_cache_hits += 1

                if job is not None:
                    normalized.append(
                        job
                    )

        final = {}

        for job in normalized:
            key = cls.normalize_text(
                job.get(
                    "external_id"
                )
                or job.get(
                    "posting_url"
                )
            )

            if not key:
                continue

            final[key] = job

        prepared_jobs = list(
            final.values()
        )

        stats = {
            "teams_attempted": len(
                cls.tech_teams
            ),
            "teams_succeeded": len(
                team_results
            ),
            "teams_failed": len(
                team_errors
            ),
            "listing_requests": (
                listing_requests
            ),
            "raw_listings": (
                raw_listing_count
            ),
            "unique_listings": (
                len(listings)
            ),
            "role_candidates": (
                len(role_candidates)
            ),
            "details_normalized": (
                len(prepared_jobs)
            ),
            "detail_requests": (
                len(role_candidates)
                - detail_cache_hits
            ),
            "detail_cache_hits": (
                detail_cache_hits
            ),
            "detail_errors": (
                detail_errors
            ),
            "max_age_days": (
                max_age_days
            ),
            "team_errors": (
                team_errors
            ),
        }

        print(
            "APPLE JOBS FEED | "
            f"Teams: "
            f"{stats['teams_succeeded']}/"
            f"{stats['teams_attempted']} | "
            f"Raw listings: "
            f"{stats['raw_listings']} | "
            f"Unique listings: "
            f"{stats['unique_listings']} | "
            f"Role candidates: "
            f"{stats['role_candidates']} | "
            f"Normalized: "
            f"{stats['details_normalized']} | "
            f"Listing requests: "
            f"{stats['listing_requests']} | "
            f"Detail requests: "
            f"{stats['detail_requests']} | "
            f"Detail cache hits: "
            f"{stats['detail_cache_hits']} | "
            f"Detail errors: "
            f"{stats['detail_errors']} | "
            f"Team errors: "
            f"{stats['teams_failed']}"
        )

        return (
            prepared_jobs,
            stats,
        )

    def prepare(
        self,
        profiles,
    ):
        source_class = type(self)
        signature = (
            source_class.profile_signature(
                profiles
            )
        )

        with source_class._cache_lock:
            if (
                source_class.cache_is_fresh()
                and source_class._cached_signature
                == signature
            ):
                self._prepared_jobs = list(
                    source_class._cached_jobs
                )
                self._prepared_stats = dict(
                    source_class._cached_stats
                    or {}
                )

                print(
                    "APPLE JOBS CACHE | "
                    f"Using "
                    f"{len(self._prepared_jobs)} "
                    "normalized jobs."
                )

                return list(
                    self._prepared_jobs
                )

        jobs, stats = (
            source_class.prepare_jobs(
                profiles
            )
        )

        with source_class._cache_lock:
            source_class._cached_jobs = list(
                jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(
                    timezone.utc
                )
            )
            source_class._cached_stats = dict(
                stats
            )
            source_class._cached_signature = (
                signature
            )

        self._prepared_jobs = list(
            jobs
        )
        self._prepared_stats = dict(
            stats
        )

        return list(
            self._prepared_jobs
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if self._prepared_jobs is None:
            self.prepare(
                [profile]
            )

        matching_jobs = [
            job
            for job
            in self._prepared_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "APPLE JOBS SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Evaluated: "
            f"{len(self._prepared_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
