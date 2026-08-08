
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import clean_html_text
from services.job_sources.job_match_service import (
    get_requested_experience_levels,
    job_matches_profile,
    matches_role_title,
)
from services.job_sources.workday_crawler import WorkdayCrawler


class WorkdayJobSource(BaseJobSource):
    source_name = "Workday"
    source_type = "workday"
    requires_company_config = True

    max_search_terms = 12
    max_detail_candidates_per_profile = 300
    max_detail_workers = 5

    explicit_title_level_patterns = (
        (
            "manager",
            re.compile(
                r"\b(?:engineering\s+manager|manager|director|"
                r"head\s+of|vice\s+president|vp)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "principal",
            re.compile(r"\bprincipal\b", re.IGNORECASE),
        ),
        (
            "staff",
            re.compile(r"\bstaff\b", re.IGNORECASE),
        ),
        (
            "lead",
            re.compile(
                r"\b(?:tech(?:nical)?\s+lead|lead)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "senior",
            re.compile(
                r"\b(?:senior|sr\.?)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "mid",
            re.compile(
                r"\b(?:mid(?:[-\s]+level)?|intermediate)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "junior",
            re.compile(
                r"\b(?:junior|jr\.?)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "entry",
            re.compile(
                r"\b(?:entry(?:[-\s]+level)?|new\s+grad(?:uate)?|"
                r"graduate)\b",
                re.IGNORECASE,
            ),
        ),
        (
            "intern",
            re.compile(
                r"\b(?:intern|internship|co[-\s]?op|student)\b",
                re.IGNORECASE,
            ),
        ),
    )

    generic_search_terms = {
        "administrator",
        "developer",
        "engineer",
        "intern",
        "internship",
        "support",
        "systems",
        "technology",
        "technical",
        "it",
    }

    def fetch_company_jobs(
        self,
        board_url,
        search_terms=None,
    ):
        if not search_terms:
            return (
                WorkdayCrawler
                .fetch_validation_listings(
                    board_url
                )
            )

        return WorkdayCrawler.fetch_listings(
            board_url,
            search_terms,
        )

    def fetch_validation_jobs(self, board_url):
        return (
            WorkdayCrawler
            .fetch_validation_listings(
                board_url
            )
        )

    @staticmethod
    def parse_profile_keywords(profile):
        raw_value = getattr(
            profile,
            "keywords",
            "",
        )

        return [
            item.strip()
            for item in re.split(
                r"[\n,]+",
                str(raw_value or ""),
            )
            if item.strip()
        ]

    @staticmethod
    def normalize_search_phrase(value):
        value = re.sub(
            r"\b(?:senior|sr\.?|junior|jr\.?|entry(?:[-\s]+level)?|"
            r"internship|intern|mid(?:[-\s]+level)?|staff|principal|"
            r"lead|manager)\b",
            "",
            str(value or ""),
            flags=re.IGNORECASE,
        )

        value = value.replace(
            "fullstack",
            "full stack",
        ).replace(
            "full-stack",
            "full stack",
        )

        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip(" -")

    @classmethod
    def build_search_terms(cls, profile):
        keywords = cls.parse_profile_keywords(
            profile
        )

        specific_terms = []
        broad_terms = []
        seen = set()

        for keyword in keywords:
            term = cls.normalize_search_phrase(
                keyword
            )
            lowered = term.lower()

            if (
                len(lowered) < 2
                or lowered in seen
            ):
                continue

            seen.add(lowered)

            if lowered in cls.generic_search_terms:
                broad_terms.append(term)
            else:
                specific_terms.append(term)

        terms = (
            specific_terms
            + broad_terms
        )[:cls.max_search_terms]

        if not terms:
            raise ValueError(
                "Workday search could not derive "
                "a usable query from this profile's keywords."
            )

        return terms

    @staticmethod
    def normalize_employment_type(value):
        normalized = re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip().lower()

        mappings = {
            "full time": "Full-time",
            "full-time": "Full-time",
            "part time": "Part-time",
            "part-time": "Part-time",
            "intern": "Internship",
            "internship": "Internship",
            "contract": "Contract",
            "contractor": "Contract",
            "temporary": "Temporary",
        }

        return mappings.get(
            normalized,
            value or None,
        )

    @staticmethod
    def normalize_workplace_type(value):
        normalized = re.sub(
            r"\s+",
            " ",
            str(value or ""),
        ).strip().lower()

        if not normalized:
            return None

        if "remote" in normalized:
            return "remote"

        if (
            "hybrid" in normalized
            or "flex" in normalized
        ):
            return "hybrid"

        if (
            "office" in normalized
            or "on-site" in normalized
            or "onsite" in normalized
        ):
            return "on-site"

        return None

    @classmethod
    def normalize_detail_job(
        cls,
        summary,
        detail_payload,
        company_name,
    ):
        info = (
            detail_payload.get(
                "jobPostingInfo"
            )
            or {}
        )

        if not isinstance(info, dict):
            info = {}

        primary_location = (
            info.get("location")
            or summary.get("location")
        )

        additional_locations = (
            info.get("additionalLocations")
            or []
        )

        if not isinstance(
            additional_locations,
            list,
        ):
            additional_locations = []

        locations = []

        if primary_location:
            locations.append(
                str(primary_location)
            )

        for location in additional_locations:
            location = str(
                location or ""
            ).strip()

            if (
                location
                and location not in locations
            ):
                locations.append(location)

        location_text = (
            " | ".join(locations)
            if locations
            else None
        )

        remote_type = (
            info.get("remoteType")
            or info.get("workplaceType")
        )

        workplace_type = (
            cls.normalize_workplace_type(
                remote_type
            )
        )

        external_id = (
            info.get("jobReqId")
            or info.get("jobPostingId")
            or summary.get("external_id")
        )

        title = (
            info.get("title")
            or summary.get("position_title")
            or "Untitled Position"
        )

        posting_url = summary.get(
            "posting_url"
        )

        return {
            "source": cls.source_name,
            "external_id": (
                str(external_id)
                if external_id
                else None
            ),
            "company_name": company_name,
            "position_title": title,
            "location": location_text,
            "employment_type": (
                cls.normalize_employment_type(
                    info.get("timeType")
                )
            ),
            "salary": None,
            "visa_sponsorship": "Unknown",
            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": clean_html_text(
                info.get("jobDescription")
            ),
            "published_at": info.get(
                "startDate"
            ),
            "workplace_type": workplace_type,
            "is_remote": (
                workplace_type == "remote"
            ),
            "workday_remote_type": remote_type,
        }

    @staticmethod
    def summary_for_role_check(
        summary,
        company_name,
    ):
        return {
            "source": "Workday",
            "company_name": company_name,
            "position_title": summary.get(
                "position_title"
            ),
            "location": summary.get(
                "location"
            ),
            "posting_url": summary.get(
                "posting_url"
            ),
            "job_description": None,
        }

    @classmethod
    def explicit_title_experience_level(
        cls,
        title,
    ):
        title = str(
            title or ""
        ).strip()

        if not title:
            return None

        for level, pattern in cls.explicit_title_level_patterns:
            if pattern.search(title):
                return level

        return None

    @classmethod
    def title_experience_matches_profile(
        cls,
        summary,
        profile,
    ):
        requested_levels = (
            get_requested_experience_levels(
                profile
            )
        )

        if not requested_levels:
            return True

        explicit_level = (
            cls.explicit_title_experience_level(
                summary.get(
                    "position_title"
                )
            )
        )

        if explicit_level is None:
            return True

        return (
            explicit_level in requested_levels
        )

    def search(
        self,
        profile,
        source_config=None,
    ):
        if source_config is None:
            raise ValueError(
                "Workday requires a company source configuration."
            )

        board_url = source_config.source_identifier

        if not board_url:
            raise ValueError(
                "Workday requires a career-board URL."
            )

        company_name = (
            source_config.company_name
            or "Unknown Company"
        ).strip()

        search_terms = self.build_search_terms(
            profile
        )

        print(
            "WORKDAY PROFILE QUERIES | "
            f"Company: {company_name} | "
            f"Queries: {search_terms}"
        )

        summaries = self.fetch_company_jobs(
            board_url,
            search_terms=search_terms,
        )

        role_candidates = [
            summary
            for summary in summaries
            if matches_role_title(
                self.summary_for_role_check(
                    summary,
                    company_name,
                ),
                profile,
            )
        ]

        experience_candidates = [
            summary
            for summary in role_candidates
            if self.title_experience_matches_profile(
                summary,
                profile,
            )
        ]

        experience_rejected = (
            len(role_candidates)
            - len(experience_candidates)
        )

        print(
            "WORKDAY PRE-DETAIL FILTER | "
            f"Company: {company_name} | "
            f"Role candidates: {len(role_candidates)} | "
            f"Explicit experience rejected: {experience_rejected} | "
            f"Detail candidates: {len(experience_candidates)}"
        )

        detail_candidates = experience_candidates

        if (
            len(detail_candidates)
            > self.max_detail_candidates_per_profile
        ):
            print(
                "WORKDAY DETAIL LIMIT | "
                f"Company: {company_name} | "
                f"Detail candidates: {len(detail_candidates)} | "
                f"Enriching first "
                f"{self.max_detail_candidates_per_profile}."
            )

            detail_candidates = (
                detail_candidates[
                    :self.max_detail_candidates_per_profile
                ]
            )

        normalized_jobs = []

        with ThreadPoolExecutor(
            max_workers=self.max_detail_workers
        ) as executor:
            future_map = {
                executor.submit(
                    WorkdayCrawler.fetch_detail,
                    board_url,
                    summary["externalPath"],
                ): summary
                for summary in detail_candidates
                if summary.get("externalPath")
            }

            for future in as_completed(
                future_map
            ):
                summary = future_map[future]

                try:
                    detail_payload = (
                        future.result()
                    )

                    normalized_job = (
                        self.normalize_detail_job(
                            summary,
                            detail_payload,
                            company_name,
                        )
                    )

                except Exception as error:
                    print(
                        "WORKDAY DETAIL ERROR | "
                        f"Company: {company_name} | "
                        f"URL: {summary.get('posting_url')} | "
                        f"Error: {error}"
                    )
                    continue

                normalized_jobs.append(
                    normalized_job
                )

        matching_jobs = [
            job
            for job in normalized_jobs
            if job_matches_profile(
                job,
                profile,
            )
        ]

        print(
            "WORKDAY SEARCH COMPLETE | "
            f"Company: {company_name} | "
            f"Targeted listings: {len(summaries)} | "
            f"Role candidates: {len(role_candidates)} | "
            f"Detail candidates: {len(detail_candidates)} | "
            f"Details normalized: {len(normalized_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
