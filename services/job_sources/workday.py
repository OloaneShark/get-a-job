
import re
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
)
from services.job_sources.job_match_service import (
    job_matches_profile,
    matches_role_title,
)
from services.job_sources.workday_crawler import (
    WorkdayCrawler,
)


class WorkdayJobSource(BaseJobSource):
    """
    Job Ad Infinitum adapter for Workday.

    WorkdayCrawler handles Workday-specific HTTP,
    pagination, and detail retrieval.

    This adapter handles:
    - Job Ad Infinitum normalization.
    - Employment/workplace normalization.
    - Role pre-filtering.
    - Profile matching.
    - The standard BaseJobSource search() interface.
    """

    source_name = "Workday"
    source_type = "workday"
    requires_company_config = True

    max_detail_candidates_per_profile = 300
    max_detail_workers = 5

    def fetch_company_jobs(
        self,
        board_url,
    ):
        """
        Used by source validation and by search().

        Returns lightweight Workday listing records.
        """

        return WorkdayCrawler.fetch_listings(
            board_url
        )

    @staticmethod
    def normalize_employment_type(
        value,
    ):
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
    def normalize_workplace_type(
        value,
    ):
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
        """
        Convert a Workday job detail response into
        Job Ad Infinitum's normalized job dictionary.
        """

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
            info.get(
                "additionalLocations"
            )
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
                locations.append(
                    location
                )

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
            or summary.get(
                "position_title"
            )
            or "Untitled Position"
        )

        posting_url = (
            summary.get("posting_url")
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
            "job_description": (
                clean_html_text(
                    info.get(
                        "jobDescription"
                    )
                )
            ),
            "published_at": (
                info.get("startDate")
            ),
            "workplace_type": (
                workplace_type
            ),
            "is_remote": (
                workplace_type
                == "remote"
            ),
            "workday_remote_type": (
                remote_type
            ),
        }

    @staticmethod
    def summary_for_role_check(
        summary,
        company_name,
    ):
        """
        Build the minimum normalized record needed by
        matches_role_title() before detail requests.

        This prevents us from downloading every job detail
        from a large Workday board when most titles are
        irrelevant to the profile.
        """

        return {
            "source": "Workday",
            "company_name": company_name,
            "position_title": (
                summary.get(
                    "position_title"
                )
            ),
            "location": (
                summary.get("location")
            ),
            "posting_url": (
                summary.get(
                    "posting_url"
                )
            ),
            "job_description": None,
        }

    def search(
        self,
        profile,
        source_config=None,
    ):
        if source_config is None:
            raise ValueError(
                "Workday requires a company "
                "source configuration."
            )

        board_url = (
            source_config.source_identifier
        )

        if not board_url:
            raise ValueError(
                "Workday requires a career-board URL."
            )

        company_name = (
            source_config.company_name
            or "Unknown Company"
        ).strip()

        summaries = self.fetch_company_jobs(
            board_url
        )

        # First filter by title using lightweight listing
        # data. We only fetch full detail for titles that
        # have a chance of matching this profile.
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

        if (
            len(role_candidates)
            > self.max_detail_candidates_per_profile
        ):
            print(
                "WORKDAY DETAIL LIMIT | "
                f"Company: {company_name} | "
                f"Role candidates: "
                f"{len(role_candidates)} | "
                f"Enriching first "
                f"{self.max_detail_candidates_per_profile}."
            )

            role_candidates = (
                role_candidates[
                    :self.max_detail_candidates_per_profile
                ]
            )

        normalized_jobs = []

        # Workday job-detail requests are independent, so
        # a small worker pool keeps large boards reasonable
        # without hammering the source.
        with ThreadPoolExecutor(
            max_workers=self.max_detail_workers
        ) as executor:
            future_map = {
                executor.submit(
                    WorkdayCrawler.fetch_detail,
                    board_url,
                    summary[
                        "externalPath"
                    ],
                ): summary
                for summary
                in role_candidates
                if summary.get(
                    "externalPath"
                )
            }

            for future in as_completed(
                future_map
            ):
                summary = future_map[
                    future
                ]

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
                        f"Company: "
                        f"{company_name} | "
                        f"URL: "
                        f"{summary.get('posting_url')} | "
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
            f"Listings: {len(summaries)} | "
            f"Role candidates: "
            f"{len(role_candidates)} | "
            f"Details normalized: "
            f"{len(normalized_jobs)} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
