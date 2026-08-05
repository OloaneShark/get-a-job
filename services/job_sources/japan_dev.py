
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_html
from services.job_sources.job_match_service import job_matches_profile


class JapanDevJobSource(BaseJobSource):
    source_name = "Japan Dev"
    source_type = "japan_dev"
    requires_company_config = False

    base_url = "https://japan-dev.com"
    jobs_url = f"{base_url}/jobs"

    # Japan Dev currently exposes its complete job list in the
    # server-rendered HTML. Cache the normalized results so the
    # scheduler does not crawl every detail page for every profile.
    cache_duration = timedelta(hours=6)
    max_workers = 4

    _cached_jobs = None
    _cache_fetched_at = None
    _cache_lock = threading.Lock()

    MONTH_PATTERN = re.compile(
        r"\b("
        r"January|February|March|April|May|June|"
        r"July|August|September|October|November|December"
        r")\s+\d{1,2},\s+\d{4}\b",
        re.IGNORECASE,
    )

    WORKPLACE_LABELS = {
        "worldwide": (
            "Remote",
            True,
            "worldwide",
            [],
        ),
        "anywhere in japan": (
            "Remote",
            True,
            "selected_locations",
            ["Japan"],
        ),
        "full remote": (
            "Remote",
            True,
            "selected_locations",
            ["Japan"],
        ),
        "partial remote": (
            "Hybrid",
            True,
            None,
            [],
        ),
        "no remote": (
            "On-site",
            False,
            None,
            [],
        ),
    }

    EMPLOYMENT_TYPE_MAPPING = {
        "full-time": "Full-time",
        "full time": "Full-time",
        "part-time": "Part-time",
        "part time": "Part-time",
        "contract": "Contract",
        "contractor": "Contract",
        "temporary": "Temporary",
        "intern": "Internship",
        "internship": "Internship",
        "freelance": "Contract",
    }

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

    @staticmethod
    def normalize_space(value):
        return re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip()

    @staticmethod
    def value_is_job_posting(value):
        if not isinstance(value, dict):
            return False

        posting_type = value.get("@type")

        if isinstance(posting_type, list):
            return "JobPosting" in posting_type

        return posting_type == "JobPosting"

    @classmethod
    def find_job_posting_json(cls, soup):
        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"},
        ):
            raw_value = (
                script.string
                or script.get_text()
            )

            if not raw_value:
                continue

            try:
                payload = json.loads(raw_value)
            except (TypeError, ValueError):
                continue

            candidates = (
                payload
                if isinstance(payload, list)
                else [payload]
            )

            for candidate in candidates:
                if cls.value_is_job_posting(candidate):
                    return candidate

                if not isinstance(candidate, dict):
                    continue

                graph = candidate.get("@graph")

                if not isinstance(graph, list):
                    continue

                for graph_item in graph:
                    if cls.value_is_job_posting(
                        graph_item
                    ):
                        return graph_item

        return None

    @classmethod
    def discover_job_urls(cls):
        html = fetch_html(cls.jobs_url)
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        urls = []
        seen = set()

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            absolute_url = urljoin(
                cls.base_url,
                anchor.get("href"),
            )
            parsed = urlparse(absolute_url)

            if parsed.netloc.lower() not in {
                "japan-dev.com",
                "www.japan-dev.com",
            }:
                continue

            path_parts = [
                part
                for part in parsed.path.split("/")
                if part
            ]

            # A Japan Dev job-detail URL has this form:
            # /jobs/<company-slug>/<job-slug>
            if (
                len(path_parts) != 3
                or path_parts[0].lower() != "jobs"
            ):
                continue

            clean_url = (
                f"https://japan-dev.com/"
                f"{'/'.join(path_parts)}"
            )

            if clean_url in seen:
                continue

            seen.add(clean_url)
            urls.append(clean_url)

        print(
            "JAPAN DEV LISTING DISCOVERY | "
            f"Unique job URLs: {len(urls)}"
        )

        return urls

    @classmethod
    def extract_page_lines(cls, soup):
        main = (
            soup.find("main")
            or soup.find("article")
            or soup.body
        )

        if main is None:
            return []

        return [
            cls.normalize_space(value)
            for value in main.stripped_strings
            if cls.normalize_space(value)
        ]

    @classmethod
    def get_header_lines(
        cls,
        lines,
        title,
    ):
        normalized_title = cls.normalize_space(
            title
        )

        for index, line in enumerate(lines):
            if line == normalized_title:
                return lines[
                    index:index + 35
                ]

        return lines[:35]

    @classmethod
    def extract_company_name(
        cls,
        soup,
        job_posting,
    ):
        organization = (
            job_posting.get(
                "hiringOrganization"
            )
            if isinstance(
                job_posting,
                dict,
            )
            else None
        )

        if isinstance(organization, dict):
            company_name = cls.normalize_space(
                organization.get("name")
            )

            if company_name:
                return company_name

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            parsed = urlparse(
                urljoin(
                    cls.base_url,
                    anchor.get("href"),
                )
            )
            path_parts = [
                part
                for part in parsed.path.split("/")
                if part
            ]

            if (
                len(path_parts) == 2
                and path_parts[0] == "companies"
            ):
                company_name = cls.normalize_space(
                    anchor.get_text(
                        " ",
                        strip=True,
                    )
                )

                if company_name:
                    return company_name

        return "Unknown Company"

    @classmethod
    def normalize_json_location(
        cls,
        job_posting,
    ):
        if not isinstance(job_posting, dict):
            return None

        raw_locations = job_posting.get(
            "jobLocation"
        )
        locations = (
            raw_locations
            if isinstance(raw_locations, list)
            else [raw_locations]
        )

        parts = []

        for item in locations:
            if not isinstance(item, dict):
                continue

            address = item.get("address") or {}

            if not isinstance(address, dict):
                continue

            for key in (
                "addressLocality",
                "addressRegion",
                "addressCountry",
            ):
                value = cls.normalize_space(
                    address.get(key)
                )

                if value == "JP":
                    value = "Japan"

                if value and value not in parts:
                    parts.append(value)

        return (
            ", ".join(parts)
            if parts
            else None
        )

    @classmethod
    def extract_visible_location(
        cls,
        header_lines,
    ):
        workplace_index = None

        for index, line in enumerate(
            header_lines
        ):
            if (
                line.lower()
                in cls.WORKPLACE_LABELS
            ):
                workplace_index = index
                break

        if (
            workplace_index is not None
            and workplace_index > 0
        ):
            candidate = cls.normalize_space(
                header_lines[
                    workplace_index - 1
                ]
            )

            if candidate:
                return candidate

        for line in header_lines:
            lowered = line.lower()

            if (
                "tokyo" in lowered
                or "osaka" in lowered
                or "nagoya" in lowered
                or "fukuoka" in lowered
                or "remote" in lowered
            ):
                return line

        return "Japan"

    @classmethod
    def extract_workplace_details(
        cls,
        header_lines,
    ):
        for line in header_lines:
            details = cls.WORKPLACE_LABELS.get(
                line.lower()
            )

            if details:
                return details

        return (
            "On-site",
            False,
            None,
            [],
        )

    @classmethod
    def normalize_employment_type(
        cls,
        value,
    ):
        normalized = cls.normalize_space(
            value
        )

        if not normalized:
            return None

        enum_mapping = {
            "FULL_TIME": "Full-time",
            "PART_TIME": "Part-time",
            "CONTRACTOR": "Contract",
            "TEMPORARY": "Temporary",
            "INTERN": "Internship",
            "OTHER": "Other",
        }

        if normalized in enum_mapping:
            return enum_mapping[normalized]

        return cls.EMPLOYMENT_TYPE_MAPPING.get(
            normalized.lower(),
            normalized.replace(
                "_",
                " ",
            ).title(),
        )

    @classmethod
    def extract_employment_type(
        cls,
        header_lines,
        job_posting,
    ):
        structured_value = (
            job_posting.get(
                "employmentType"
            )
            if isinstance(
                job_posting,
                dict,
            )
            else None
        )

        if isinstance(
            structured_value,
            list,
        ):
            structured_value = next(
                (
                    value
                    for value
                    in structured_value
                    if value
                ),
                None,
            )

        normalized = (
            cls.normalize_employment_type(
                structured_value
            )
        )

        if normalized:
            return normalized

        for line in header_lines:
            matched = (
                cls.EMPLOYMENT_TYPE_MAPPING.get(
                    line.lower()
                )
            )

            if matched:
                return matched

        return None

    @staticmethod
    def format_number(value):
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None

        if numeric_value.is_integer():
            return f"{numeric_value:,.0f}"

        return (
            f"{numeric_value:,.2f}"
            .rstrip("0")
            .rstrip(".")
        )

    @classmethod
    def format_json_salary(
        cls,
        job_posting,
    ):
        if not isinstance(job_posting, dict):
            return None

        base_salary = job_posting.get(
            "baseSalary"
        )

        if not isinstance(base_salary, dict):
            return None

        currency = cls.normalize_space(
            base_salary.get("currency")
        ) or "JPY"
        value = base_salary.get("value") or {}

        if not isinstance(value, dict):
            return None

        minimum = cls.format_number(
            value.get("minValue")
        )
        maximum = cls.format_number(
            value.get("maxValue")
        )
        exact_value = cls.format_number(
            value.get("value")
        )
        unit = cls.normalize_space(
            value.get("unitText")
        ).lower()

        suffix = {
            "year": "per year",
            "month": "per month",
            "hour": "per hour",
        }.get(
            unit,
            unit,
        )

        if minimum and maximum:
            return (
                f"{currency} {minimum} - "
                f"{maximum} {suffix}"
            ).strip()

        if minimum:
            return (
                f"From {currency} {minimum} "
                f"{suffix}"
            ).strip()

        if maximum:
            return (
                f"Up to {currency} {maximum} "
                f"{suffix}"
            ).strip()

        if exact_value:
            return (
                f"{currency} {exact_value} "
                f"{suffix}"
            ).strip()

        return None

    @classmethod
    def extract_visible_salary(
        cls,
        lines,
    ):
        for line in lines:
            normalized = cls.normalize_space(
                line
            )

            if (
                "¥" in normalized
                and any(
                    marker in normalized.lower()
                    for marker in (
                        "/yr",
                        " per year",
                        "m ~",
                        "m or more",
                    )
                )
            ):
                return normalized

        return None

    @classmethod
    def parse_visible_date(
        cls,
        header_lines,
    ):
        for line in header_lines:
            match = cls.MONTH_PATTERN.search(
                line
            )

            if not match:
                continue

            try:
                parsed = datetime.strptime(
                    match.group(0),
                    "%B %d, %Y",
                )
            except ValueError:
                continue

            return parsed.date().isoformat()

        return None

    @classmethod
    def extract_published_at(
        cls,
        header_lines,
        job_posting,
    ):
        visible_date = cls.parse_visible_date(
            header_lines
        )

        if visible_date:
            return visible_date

        if isinstance(job_posting, dict):
            return (
                job_posting.get("datePosted")
                or job_posting.get(
                    "datePublished"
                )
            )

        return None

    @classmethod
    def detect_candidate_location(
        cls,
        page_text,
    ):
        lowered = page_text.lower()

        negative_phrases = (
            "apply from japan only",
            "japan residents only",
            "residents only",
            "must currently reside in japan",
            "only open to candidates in japan",
        )

        if any(
            phrase in lowered
            for phrase in negative_phrases
        ):
            return "japan only"

        positive_phrases = (
            "apply from anywhere",
            "apply from abroad",
            "overseas applicants welcome",
            "open to overseas applicants",
            "applications from overseas",
        )

        if any(
            phrase in lowered
            for phrase in positive_phrases
        ):
            return "anywhere"

        return None

    @classmethod
    def detect_overseas_status(
        cls,
        page_text,
    ):
        candidate_location = (
            cls.detect_candidate_location(
                page_text
            )
        )

        if candidate_location == "japan only":
            return "No"

        if candidate_location == "anywhere":
            return "Yes"

        return "Unknown"

    @classmethod
    def detect_visa_sponsorship(
        cls,
        page_text,
    ):
        lowered = page_text.lower()

        negative_phrases = (
            "no relocation to japan",
            "no visa sponsorship from overseas",
            "no visa sponsorship",
            "visa sponsorship is not available",
            "cannot sponsor visas",
            "does not sponsor visas",
        )

        if any(
            phrase in lowered
            for phrase in negative_phrases
        ):
            return "No"

        positive_phrases = (
            "overseas visa sponsorship supported",
            "relocation to japan",
            "visa sponsorship available",
            "visa sponsorship provided",
            "visa support available",
            "sponsor your visa",
        )

        if any(
            phrase in lowered
            for phrase in positive_phrases
        ):
            return "Yes"

        return "Unknown"

    @classmethod
    def extract_experience_level(
        cls,
        lines,
    ):
        for index, line in enumerate(lines):
            if (
                line.lower()
                != "minimum experience"
            ):
                continue

            for candidate in lines[
                index + 1:index + 5
            ]:
                normalized = cls.normalize_space(
                    candidate
                )

                if normalized:
                    return normalized

        return None

    @classmethod
    def extract_language_level(
        cls,
        lines,
        language,
    ):
        prefix = f"{language.lower()}:"

        for line in lines:
            lowered = line.lower()

            if lowered.startswith(prefix):
                return cls.normalize_space(
                    line.split(
                        ":",
                        1,
                    )[1].replace(
                        "👍",
                        "",
                    )
                )

        return None

    @classmethod
    def extract_departments(
        cls,
        job_posting,
    ):
        if not isinstance(job_posting, dict):
            return []

        departments = []

        for field_name in (
            "skills",
            "occupationalCategory",
        ):
            values = job_posting.get(
                field_name
            )

            if isinstance(values, str):
                values = re.split(
                    r"[,|]",
                    values,
                )

            if not isinstance(
                values,
                (list, tuple, set),
            ):
                continue

            for value in values:
                normalized = cls.normalize_space(
                    value
                )

                if (
                    normalized
                    and normalized
                    not in departments
                ):
                    departments.append(
                        normalized
                    )

        return departments

    @classmethod
    def extract_job_description(
        cls,
        lines,
        title,
        company_name,
        job_posting,
    ):
        if isinstance(job_posting, dict):
            structured_description = (
                clean_html_text(
                    job_posting.get(
                        "description"
                    )
                )
            )

            if structured_description:
                return structured_description

        title = cls.normalize_space(title)
        company_name = cls.normalize_space(
            company_name
        )
        start_index = None

        for index, line in enumerate(lines):
            if line == title:
                start_index = index + 1
                break

        if start_index is None:
            return None

        end_index = len(lines)

        for index in range(
            start_index + 10,
            len(lines),
        ):
            line = lines[index]
            lowered = line.lower()

            if lowered.startswith("apply now"):
                end_index = index
                break

            if (
                company_name
                and line == f"About {company_name}"
            ):
                end_index = index
                break

            if lowered.startswith("jobs at "):
                end_index = index
                break

            if line == "Latest Tech Jobs 🇯🇵":
                end_index = index
                break

        description_lines = lines[
            start_index:end_index
        ]

        return (
            "\n".join(description_lines)
            or None
        )

    @classmethod
    def find_apply_url(
        cls,
        soup,
        posting_url,
    ):
        fallback_url = None

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            text = cls.normalize_space(
                anchor.get_text(
                    " ",
                    strip=True,
                )
            ).lower()

            if (
                "apply now" not in text
                and text != "apply"
            ):
                continue

            absolute_url = urljoin(
                cls.base_url,
                anchor.get("href"),
            )
            parsed = urlparse(absolute_url)

            if not parsed.scheme.startswith(
                "http"
            ):
                continue

            if absolute_url == posting_url:
                continue

            if parsed.netloc.lower() not in {
                "japan-dev.com",
                "www.japan-dev.com",
            }:
                return absolute_url

            fallback_url = absolute_url

        return fallback_url or posting_url

    @classmethod
    def parse_job_page(
        cls,
        posting_url,
    ):
        html = fetch_html(posting_url)
        soup = BeautifulSoup(
            html,
            "html.parser",
        )
        title_element = soup.find("h1")

        if title_element is None:
            return None

        title = cls.normalize_space(
            title_element.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            return None

        lines = cls.extract_page_lines(soup)
        header_lines = cls.get_header_lines(
            lines,
            title,
        )
        page_text = "\n".join(lines)
        job_posting = (
            cls.find_job_posting_json(soup)
            or {}
        )
        company_name = (
            cls.extract_company_name(
                soup,
                job_posting,
            )
        )
        location = (
            cls.normalize_json_location(
                job_posting
            )
            or cls.extract_visible_location(
                header_lines
            )
        )
        (
            workplace_type,
            is_remote,
            remote_candidate_scope,
            remote_allowed_locations,
        ) = cls.extract_workplace_details(
            header_lines
        )
        visa_sponsorship = (
            cls.detect_visa_sponsorship(
                page_text
            )
        )
        overseas_status = (
            cls.detect_overseas_status(
                page_text
            )
        )
        candidate_location = (
            cls.detect_candidate_location(
                page_text
            )
        )
        experience_level = (
            cls.extract_experience_level(
                lines
            )
        )
        japanese_level = (
            cls.extract_language_level(
                lines,
                "Japanese",
            )
        )
        english_level = (
            cls.extract_language_level(
                lines,
                "English",
            )
        )
        description = (
            cls.extract_job_description(
                lines,
                title,
                company_name,
                job_posting,
            )
        )

        metadata_lines = [
            f"Overseas applicants: {overseas_status}",
            f"Visa sponsorship: {visa_sponsorship}",
            f"Workplace type: {workplace_type}",
        ]

        if experience_level:
            metadata_lines.append(
                "Minimum experience: "
                f"{experience_level}"
            )

        if japanese_level:
            metadata_lines.append(
                "Japanese level: "
                f"{japanese_level}"
            )

        if english_level:
            metadata_lines.append(
                "English level: "
                f"{english_level}"
            )

        metadata = (
            "Job conditions\n"
            + "\n".join(metadata_lines)
        )
        normalized_description = "\n\n".join(
            value
            for value in (
                description,
                metadata,
            )
            if value
        ) or None
        parsed_url = urlparse(posting_url)

        return {
            "source": cls.source_name,
            "external_id": (
                parsed_url.path.strip("/")
            ),
            "company_name": company_name,
            "position_title": title,
            "location": location or "Japan",
            "employment_type": (
                cls.extract_employment_type(
                    header_lines,
                    job_posting,
                )
            ),
            "salary": (
                cls.format_json_salary(
                    job_posting
                )
                or cls.extract_visible_salary(
                    lines
                )
            ),
            "visa_sponsorship": visa_sponsorship,
            "overseas_applicant_status": (
                overseas_status
            ),
            "posting_url": posting_url,
            "apply_url": cls.find_apply_url(
                soup,
                posting_url,
            ),
            "job_description": (
                normalized_description
            ),
            "departments": (
                cls.extract_departments(
                    job_posting
                )
            ),
            "offices": [],
            "is_remote": is_remote,
            "workplace_type": workplace_type,
            "remote_candidate_scope": (
                remote_candidate_scope
            ),
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "candidate_location": (
                candidate_location
            ),
            "experience_level": (
                experience_level
            ),
            "published_at": (
                cls.extract_published_at(
                    header_lines,
                    job_posting,
                )
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def fetch_jobs(cls):
        urls = cls.discover_job_urls()
        jobs = []
        completed = 0

        with ThreadPoolExecutor(
            max_workers=cls.max_workers
        ) as executor:
            future_map = {
                executor.submit(
                    cls.parse_job_page,
                    url,
                ): url
                for url in urls
            }

            for future in as_completed(
                future_map
            ):
                completed += 1
                url = future_map[future]

                try:
                    job = future.result()

                    if job:
                        jobs.append(job)

                except Exception as error:
                    print(
                        "JAPAN DEV JOB PAGE FAILED | "
                        f"URL: {url} | "
                        f"Error: {error}"
                    )

                if (
                    completed % 20 == 0
                    or completed == len(urls)
                ):
                    print(
                        "JAPAN DEV CRAWL PROGRESS | "
                        f"{completed}/{len(urls)} "
                        "pages processed."
                    )

        return jobs

    def get_cached_jobs(self):
        source_class = type(self)

        with source_class._cache_lock:
            if source_class.cache_is_fresh():
                print(
                    "JAPAN DEV CACHE | "
                    f"Using "
                    f"{len(source_class._cached_jobs)} "
                    "cached jobs."
                )

                return list(
                    source_class._cached_jobs
                )

            normalized_jobs = (
                source_class.fetch_jobs()
            )
            normalized_jobs = [
                job
                for job in normalized_jobs
                if job.get("posting_url")
            ]

            source_class._cached_jobs = (
                normalized_jobs
            )
            source_class._cache_fetched_at = (
                datetime.now(timezone.utc)
            )

            print(
                "JAPAN DEV FEED | "
                f"Fetched "
                f"{len(normalized_jobs)} jobs."
            )

            return list(normalized_jobs)

    def search(
        self,
        profile,
        source_config=None,
    ):
        jobs = self.get_cached_jobs()

        matching_jobs = [
            job
            for job in jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "JAPAN DEV SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
    