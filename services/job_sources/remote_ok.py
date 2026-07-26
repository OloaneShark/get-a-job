
from services.job_sources.base import BaseJobSource
from services.job_sources.http_client import (
    clean_html_text,
    fetch_json,
)
from services.job_sources.job_match_service import (
    job_matches_profile,
)


class RemoteOKJobSource(BaseJobSource):
    source_name = "Remote OK"
    source_type = "remote_ok"
    requires_company_config = False

    feed_url = "https://remoteok.com/api"
    
    @staticmethod
    def is_plausible_job(job):
        title = (
            job.get("position_title")
            or ""
        ).strip()

        company = (
            job.get("company_name")
            or ""
        ).strip()

        posting_url = (
            job.get("posting_url")
            or ""
        ).strip()

        if not title or not company or not posting_url:
            return False

        rejected_titles = {
            "join our team",
            "join us",
            "come and join us",
            "apply for employment",
            "job title",
            "sample job",
            "heading",
            "life",
            "no",
        }

        if title.lower() in rejected_titles:
            return False

        if len(title) < 4:
            return False

        suspicious_phrases = {
            "how do i",
            "how keep your",
            "the mino earrings",
            "the introspect",
            "i want all the money",
            "job hunting indecision",
            "we don't currently have",
            "https ",
        }

        lowered_title = title.lower()

        if any(
            phrase in lowered_title
            for phrase in suspicious_phrases
        ):
            return False

        return True

    def fetch_jobs(self):
        payload = fetch_json(self.feed_url)

        if not isinstance(payload, list):
            raise RuntimeError(
                "Remote OK returned an unexpected response."
            )

        jobs = []

        for item in payload:
            if not isinstance(item, dict):
                continue

            # Remote OK commonly places metadata first.
            if not item.get("id"):
                continue

            if not item.get("position"):
                continue

            jobs.append(item)

        return jobs

    def normalize_job(self, raw_job):
        posting_url = (
            raw_job.get("url")
            or raw_job.get("apply_url")
        )

        description = clean_html_text(
            raw_job.get("description")
        )

        tags = raw_job.get("tags") or []

        if not isinstance(tags, list):
            tags = []

        location = (
            raw_job.get("location")
            or "Remote"
        )

        salary_min = raw_job.get("salary_min")
        salary_max = raw_job.get("salary_max")

        salary = None

        if salary_min and salary_max:
            salary = (
                f"${salary_min:,} - "
                f"${salary_max:,}"
            )
        elif salary_min:
            salary = f"From ${salary_min:,}"
        elif salary_max:
            salary = f"Up to ${salary_max:,}"

        return {
            "source": self.source_name,
            "external_id": str(raw_job.get("id")),
            "company_name": (
                raw_job.get("company")
                or "Unknown Company"
            ),
            "position_title": (
                raw_job.get("position")
                or "Untitled Position"
            ),
            "location": location,
            "employment_type": "Full-time",
            "salary": salary,

            # Remote OK normally does not provide
            # dependable sponsorship information.
            "visa_sponsorship": "unknown",

            "posting_url": posting_url,
            "apply_url": posting_url,
            "job_description": description,
            "departments": tags,
            "offices": [],
            "is_remote": True,
            "workplace_type": "Remote",
            "published_at": (
                raw_job.get("date")
                or raw_job.get("epoch")
            ),
            "recruiter_name": None,
            "recruiter_email": None,
            "recruiter_contact_url": None,
            "recruiter_contact_source": None,
        }

    def search(self, profile, source_config=None):
        raw_jobs = self.fetch_jobs()
        matching_jobs = []

        print(
            f"REMOTE OK SEARCH | "
            f"Profile: {profile.name} | "
            f"Fetched: {len(raw_jobs)} | "
            f"Experience: "
            f"{profile.experience_levels or 'any'} | "
            f"Remote scope: "
            f"{profile.remote_scope or 'any'} | "
            f"Visa: "
            f"{profile.visa_preference or 'any'}"
        )

        for raw_job in raw_jobs:
            job = self.normalize_job(raw_job)

            if not self.is_plausible_job(job):
                print(
                    f"REMOTE OK INVALID RECORD | "
                    f"Title: {job.get('position_title')} | "
                    f"Company: {job.get('company_name')}"
                )
                continue

            if not job_matches_profile(
                job,
                profile
            ):
                continue

            matching_jobs.append(job)

        print(
            f"REMOTE OK SEARCH COMPLETE | "
            f"Profile: {profile.name} | "
            f"Matched: {len(matching_jobs)}"
        )

        return matching_jobs
