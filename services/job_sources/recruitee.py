
import re
from urllib.parse import urlparse

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text, fetch_json
from services.job_sources.job_match_service import job_matches_profile


class RecruiteeJobSource(BaseJobSource):
    source_name = "Recruitee"
    source_type = "recruitee"
    requires_company_config = True

    blocked_subdomains = {
        "api",
        "app",
        "docs",
        "help",
        "status",
        "support",
        "www",
    }

    @classmethod
    def extract_company_slug(cls, value):
        text = str(value or "").strip()

        if not text:
            raise ValueError(
                "A Recruitee careers URL or "
                "company subdomain is required."
            )

        if "://" not in text:
            if "." not in text and "/" not in text:
                slug = text.lower()
            else:
                text = f"https://{text}"
                hostname = (
                    urlparse(text).hostname
                    or ""
                ).lower()
                slug = cls.slug_from_hostname(
                    hostname
                )
        else:
            hostname = (
                urlparse(text).hostname
                or ""
            ).lower()
            slug = cls.slug_from_hostname(
                hostname
            )

        if not re.fullmatch(
            r"[a-z0-9][a-z0-9._-]{1,99}",
            slug,
        ):
            raise ValueError(
                "Invalid Recruitee company "
                "subdomain."
            )

        if slug in cls.blocked_subdomains:
            raise ValueError(
                "The URL is not a Recruitee "
                "company careers site."
            )

        return slug

    @classmethod
    def slug_from_hostname(
        cls,
        hostname,
    ):
        hostname = str(
            hostname or ""
        ).strip().lower()

        suffix = ".recruitee.com"

        if (
            not hostname.endswith(suffix)
            or hostname.endswith(
                ".s.recruitee.com"
            )
        ):
            raise ValueError(
                "The URL is not a supported "
                "Recruitee careers site."
            )

        slug = hostname[
            :-len(suffix)
        ].strip(".")

        if not slug or "." in slug:
            raise ValueError(
                "The URL is not a standard "
                "Recruitee company careers site."
            )

        return slug

    @classmethod
    def board_url(cls, company_slug):
        slug = cls.extract_company_slug(
            company_slug
        )
        return (
            f"https://{slug}.recruitee.com"
        )

    @classmethod
    def api_url(cls, company_slug):
        return (
            f"{cls.board_url(company_slug)}"
            "/api/offers/"
        )

    @classmethod
    def fetch_company_jobs(
        cls,
        company_slug,
    ):
        slug = cls.extract_company_slug(
            company_slug
        )

        payload = fetch_json(
            cls.api_url(slug),
            headers={
                "Accept": "application/json",
            },
            timeout=30,
        )

        if isinstance(payload, list):
            jobs = payload
        elif isinstance(payload, dict):
            jobs = (
                payload.get("offers")
                or payload.get("jobs")
                or payload.get("results")
                or []
            )
        else:
            raise RuntimeError(
                "Recruitee returned an "
                "unexpected response."
            )

        if not isinstance(jobs, list):
            raise RuntimeError(
                "Recruitee returned invalid "
                "jobs data."
            )

        return [
            job
            for job in jobs
            if isinstance(job, dict)
        ]

    @staticmethod
    def value_name(value):
        if isinstance(value, dict):
            for key in (
                "name",
                "title",
                "label",
                "text",
            ):
                result = str(
                    value.get(key)
                    or ""
                ).strip()

                if result:
                    return result

            return None

        result = str(
            value or ""
        ).strip()

        return result or None

    @classmethod
    def company_name_from_offer(
        cls,
        offer,
        fallback,
    ):
        for key in (
            "company_name",
            "company",
            "organization",
        ):
            value = cls.value_name(
                offer.get(key)
            )

            if value:
                return value

        return str(
            fallback or ""
        ).strip() or "Unknown Company"

    @classmethod
    def normalize_locations(
        cls,
        offer,
    ):
        results = []
        seen = set()

        def add_location(value):
            location = str(
                value or ""
            ).strip()

            if not location:
                return

            lowered = location.lower()

            if lowered in seen:
                return

            seen.add(lowered)
            results.append(location)

        direct_location = str(
            offer.get("location")
            or ""
        ).strip()

        add_location(
            direct_location
        )

        raw_locations = offer.get(
            "locations"
        )

        if isinstance(
            raw_locations,
            list,
        ):
            for raw_location in raw_locations:
                if not isinstance(
                    raw_location,
                    dict,
                ):
                    add_location(
                        raw_location
                    )
                    continue

                pieces = []

                for key in (
                    "city",
                    "state",
                    "country",
                ):
                    value = str(
                        raw_location.get(key)
                        or ""
                    ).strip()

                    if (
                        value
                        and value not in pieces
                    ):
                        pieces.append(value)

                geographic_location = (
                    ", ".join(pieces)
                )

                if geographic_location:
                    add_location(
                        geographic_location
                    )
                    continue

                add_location(
                    cls.value_name(
                        raw_location
                    )
                )

        if not results:
            pieces = []

            for key in (
                "city",
                "state_name",
                "state",
                "country",
            ):
                value = str(
                    offer.get(key)
                    or ""
                ).strip()

                if (
                    value
                    and value not in pieces
                ):
                    pieces.append(value)

            if pieces:
                add_location(
                    ", ".join(pieces)
                )

        return results

    @staticmethod
    def normalize_employment_type(
        offer,
        title,
    ):
        values = (
            offer.get(
                "employment_type_code"
            ),
            offer.get("contract_type"),
            offer.get("employment_type"),
            offer.get("employmentType"),
        )

        mapping = {
            "full_time": "Full-time",
            "fulltime": "Full-time",
            "fulltime_permanent": "Full-time",
            "fulltime_fixed_term": "Full-time",
            "part_time": "Part-time",
            "parttime": "Part-time",
            "parttime_permanent": "Part-time",
            "parttime_fixed_term": "Part-time",
            "parttime_minijob": "Part-time",
            "contract": "Contract",
            "contractor": "Contract",
            "freelance": "Contract",
            "temporary": "Temporary",
            "temp": "Temporary",
            "seasonal": "Temporary",
            "internship": "Internship",
            "intern": "Internship",
            "apprenticeship": "Internship",
            "volunteer": "Volunteer",
        }

        for value in values:
            normalized = (
                str(value or "")
                .strip()
                .lower()
                .replace("-", "_")
                .replace(" ", "_")
            )

            if not normalized:
                continue

            if normalized in mapping:
                return mapping[
                    normalized
                ]

            readable = re.sub(
                r"_+",
                " ",
                normalized,
            ).strip()

            if readable:
                return readable.title()

        if re.search(
            r"\b(?:intern|internship)\b",
            str(title or ""),
            flags=re.IGNORECASE,
        ):
            return "Internship"

        return None

    @staticmethod
    def explicit_title_experience_level(
        title,
    ):
        normalized = re.sub(
            r"\s+",
            " ",
            str(title or "")
            .strip()
            .lower()
            .replace("-", " "),
        )

        patterns = (
            (
                "manager",
                (
                    r"\bmanager\b",
                    r"\bdirector\b",
                    r"\bhead of\b",
                    r"\bvice president\b",
                    r"\bvp\b",
                ),
            ),
            (
                "principal",
                (
                    r"\bprincipal\b",
                ),
            ),
            (
                "staff",
                (
                    r"\bstaff\b",
                ),
            ),
            (
                "lead",
                (
                    r"\blead\b",
                    r"\btech lead\b",
                    r"\btechnical lead\b",
                ),
            ),
            (
                "senior",
                (
                    r"\bsenior\b",
                    r"\bsr\.?\b",
                ),
            ),
            (
                "junior",
                (
                    r"\bjunior\b",
                    r"\bjr\.?\b",
                ),
            ),
            (
                "entry",
                (
                    r"\bentry level\b",
                    r"\bnew grad\b",
                    r"\bnew graduate\b",
                    r"\bgraduate\b",
                ),
            ),
            (
                "intern",
                (
                    r"\bintern\b",
                    r"\binternship\b",
                    r"\bco op\b",
                ),
            ),
            (
                "mid",
                (
                    r"\bmid level\b",
                    r"\bintermediate\b",
                ),
            ),
        )

        for level, level_patterns in patterns:
            if any(
                re.search(
                    pattern,
                    normalized,
                    flags=re.IGNORECASE,
                )
                for pattern in level_patterns
            ):
                return level

        return None

    @classmethod
    def normalize_experience_level(
        cls,
        offer,
        title,
    ):
        title_level = (
            cls.explicit_title_experience_level(
                title
            )
        )

        if title_level:
            return title_level

        value = (
            offer.get(
                "experience_code"
            )
            or offer.get("experience")
            or offer.get(
                "experience_level"
            )
        )

        normalized = (
            str(value or "")
            .strip()
            .lower()
            .replace("-", "_")
            .replace(" ", "_")
        )

        mapping = {
            "student_high_school": "intern",
            "student_college": "intern",
            "entry_level": "entry",
            "mid_level": "mid",
            "experienced": "senior",
            "manager": "manager",
            "senior_manager_supervisor": (
                "manager"
            ),
            "executive": "manager",
            "senior_executive": "manager",
        }

        return mapping.get(
            normalized
        )

    @staticmethod
    def humanize_code(value):
        text = (
            str(value or "")
            .strip()
            .replace("-", " ")
            .replace("_", " ")
        )

        if not text:
            return None

        return re.sub(
            r"\s+",
            " ",
            text,
        ).strip().title()

    @staticmethod
    def normalize_salary(offer):
        salary = offer.get("salary")

        if isinstance(salary, str):
            return (
                salary.strip()
                or None
            )

        if not isinstance(
            salary,
            dict,
        ):
            minimum = (
                offer.get("min_salary")
                or offer.get("salary_min")
            )
            maximum = (
                offer.get("max_salary")
                or offer.get("salary_max")
            )
            currency = (
                offer.get("currency")
                or offer.get(
                    "salary_currency"
                )
            )
            period = (
                offer.get("period")
                or offer.get(
                    "salary_period"
                )
            )
        else:
            minimum = (
                salary.get("min_salary")
                or salary.get("min")
                or salary.get("minimum")
            )
            maximum = (
                salary.get("max_salary")
                or salary.get("max")
                or salary.get("maximum")
            )
            currency = (
                salary.get("currency")
                or salary.get(
                    "currency_code"
                )
            )
            period = (
                salary.get("period")
                or salary.get("interval")
            )

        if (
            minimum is None
            and maximum is None
        ):
            return None

        values = []

        if currency:
            values.append(
                str(currency).strip()
            )

        if (
            minimum is not None
            and maximum is not None
        ):
            values.append(
                f"{minimum} - {maximum}"
            )
        elif minimum is not None:
            values.append(
                f"From {minimum}"
            )
        else:
            values.append(
                f"Up to {maximum}"
            )

        if period:
            values.append(
                f"per {period}"
            )

        return " ".join(values)

    @classmethod
    def normalize_description(
        cls,
        offer,
    ):
        parts = []

        for key in (
            "description",
            "requirements",
            "description_requirements",
        ):
            value = clean_html_text(
                offer.get(key)
            )

            if (
                value
                and value not in parts
            ):
                parts.append(value)

        return (
            "\n\n".join(parts)
            or None
        )

    @classmethod
    def normalize_job(
        cls,
        offer,
        company_name,
        company_slug,
    ):
        if not isinstance(
            offer,
            dict,
        ):
            return None

        title = str(
            offer.get("title")
            or offer.get("name")
            or "Untitled Position"
        ).strip()

        posting_url = str(
            offer.get("careers_url")
            or offer.get("url")
            or offer.get("job_url")
            or ""
        ).strip()

        slug = str(
            offer.get("slug")
            or ""
        ).strip()

        if (
            not posting_url
            and slug
        ):
            posting_url = (
                f"{cls.board_url(company_slug)}"
                f"/o/{slug}"
            )

        if not posting_url:
            return None

        apply_url = str(
            offer.get(
                "careers_apply_url"
            )
            or offer.get("apply_url")
            or offer.get("applyUrl")
            or ""
        ).strip()

        if not apply_url and slug:
            apply_url = (
                f"{cls.board_url(company_slug)}"
                f"/o/{slug}/c/new"
            )

        apply_url = (
            apply_url
            or posting_url
        )

        locations = (
            cls.normalize_locations(
                offer
            )
        )
        location = (
            " | ".join(locations)
            if locations
            else None
        )

        remote = bool(
            offer.get("remote")
            or offer.get("is_remote")
            or offer.get("isRemote")
        )
        hybrid = bool(
            offer.get("hybrid")
        )

        if hybrid:
            workplace_type = "Hybrid"
        elif remote:
            workplace_type = "Remote"
        elif offer.get("on_site") is True:
            workplace_type = "On-site"
        else:
            workplace_type = None

        description = (
            cls.normalize_description(
                offer
            )
        )

        department = cls.value_name(
            offer.get("department")
        )
        category = (
            cls.value_name(
                offer.get("category")
            )
            or cls.humanize_code(
                offer.get(
                    "category_code"
                )
            )
        )
        experience = (
            cls.normalize_experience_level(
                offer,
                title,
            )
        )
        education = cls.humanize_code(
            offer.get(
                "education_code"
            )
            or offer.get("education")
        )

        external_id = str(
            offer.get("id")
            or offer.get("guid")
            or slug
            or posting_url
        ).strip()

        remote_allowed_locations = []

        if workplace_type == "Remote":
            for value in locations:
                if not value:
                    continue

                lowered = value.lower()

                if lowered in {
                    "remote",
                    "remote job",
                }:
                    continue

                remote_allowed_locations.append(
                    value
                )

        return {
            "source": cls.source_name,
            "external_id": external_id,
            "company_name": (
                cls.company_name_from_offer(
                    offer,
                    company_name,
                )
            ),
            "position_title": title,
            "location": location,
            "employment_type": (
                cls.normalize_employment_type(
                    offer,
                    title,
                )
            ),
            "salary": (
                cls.normalize_salary(
                    offer
                )
            ),
            "visa_sponsorship": "Unknown",
            "overseas_applicant_status": (
                "Unknown"
            ),
            "posting_url": posting_url,
            "apply_url": apply_url,
            "job_description": description,
            "departments": [
                value
                for value in (
                    department,
                    category,
                )
                if value
            ],
            "offices": locations,
            "experience_level": (
                [experience]
                if experience
                else []
            ),
            "education_level": education,
            "source_category": category,
            "is_remote": (
                workplace_type == "Remote"
            ),
            "workplace_type": workplace_type,
            "remote_allowed_locations": (
                remote_allowed_locations
            ),
            "published_at": (
                offer.get("published_at")
                or offer.get("posted")
                or offer.get("created_at")
            ),
            "updated_at": (
                offer.get("updated_at")
                or offer.get("updated")
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    @classmethod
    def search_company(
        cls,
        company_slug,
        company_name,
    ):
        raw_jobs = cls.fetch_company_jobs(
            company_slug
        )
        jobs = []

        for offer in raw_jobs:
            if (
                offer.get("status")
                and str(
                    offer.get("status")
                ).lower()
                not in {
                    "published",
                    "open",
                }
            ):
                continue

            if (
                offer.get("kind")
                and str(
                    offer.get("kind")
                ).lower()
                not in {
                    "job",
                    "offer",
                }
            ):
                continue

            job = cls.normalize_job(
                offer,
                company_name,
                company_slug,
            )

            if job is not None:
                jobs.append(job)

        return jobs

    @classmethod
    def fetch_validation_jobs(
        cls,
        company_slug,
    ):
        slug = cls.extract_company_slug(
            company_slug
        )

        return cls.search_company(
            slug,
            slug,
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if source_config is None:
            raise ValueError(
                "Recruitee requires a company "
                "source configuration."
            )

        jobs = self.search_company(
            company_slug=(
                source_config
                .source_identifier
            ),
            company_name=(
                source_config.company_name
            ),
        )

        return [
            job
            for job in jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]
