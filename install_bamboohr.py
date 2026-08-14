from pathlib import Path
import sys

ROOT = Path.cwd()

SOURCE_PATH = ROOT / "services" / "job_sources" / "bamboohr.py"
REGISTRY_PATH = ROOT / "services" / "job_sources" / "registry.py"
SOURCE_UTILS_PATH = ROOT / "services" / "job_sources" / "source_utils.py"
DISCOVERY_PATH = ROOT / "services" / "job_sources" / "discovery" / "source_discovery.py"
COMMON_CRAWL_PATH = ROOT / "services" / "job_sources" / "discovery" / "common_crawl_discovery.py"
FORMS_PATH = ROOT / "forms.py"

BAMBOOHR_SOURCE = 'import re\nimport threading\nfrom datetime import datetime, timedelta, timezone\n\nfrom services.job_sources.base import BaseJobSource\nfrom services.job_sources.http_client import clean_html_text, fetch_json\nfrom services.job_sources.job_match_service import (\n    job_matches_profile,\n    matches_role_title,\n)\nfrom services.job_sources.source_utils import (\n    extract_bamboohr_company_subdomain,\n)\n\n\nclass BambooHRJobSource(BaseJobSource):\n    source_name = "BambooHR"\n    source_type = "bamboohr"\n    requires_company_config = True\n\n    cache_duration = timedelta(minutes=30)\n\n    _cache_lock = threading.Lock()\n    _listing_cache = {}\n    _detail_cache = {}\n    _company_cache = {}\n\n    @classmethod\n    def cache_get(cls, cache, key):\n        with cls._cache_lock:\n            item = cache.get(key)\n\n            if not item:\n                return None\n\n            fetched_at = item.get("fetched_at")\n\n            if (\n                fetched_at is None\n                or (\n                    datetime.now(timezone.utc)\n                    - fetched_at\n                ) >= cls.cache_duration\n            ):\n                cache.pop(key, None)\n                return None\n\n            return item.get("value")\n\n    @classmethod\n    def cache_set(cls, cache, key, value):\n        with cls._cache_lock:\n            cache[key] = {\n                "fetched_at": datetime.now(timezone.utc),\n                "value": value,\n            }\n\n        return value\n\n    @staticmethod\n    def company_base_url(company_subdomain):\n        return f"https://{company_subdomain}.bamboohr.com"\n\n    @classmethod\n    def fetch_company_info(cls, company_subdomain):\n        company_subdomain = extract_bamboohr_company_subdomain(\n            company_subdomain\n        )\n\n        cached = cls.cache_get(\n            cls._company_cache,\n            company_subdomain,\n        )\n\n        if cached is not None:\n            return cached\n\n        payload = fetch_json(\n            (\n                f"{cls.company_base_url(company_subdomain)}"\n                "/careers/company-info"\n            ),\n            timeout=30,\n        )\n\n        if not isinstance(payload, dict):\n            raise RuntimeError(\n                "BambooHR returned an unexpected company-info response."\n            )\n\n        result = payload.get("result")\n\n        if not isinstance(result, dict):\n            raise RuntimeError(\n                "BambooHR returned invalid company-info data."\n            )\n\n        return cls.cache_set(\n            cls._company_cache,\n            company_subdomain,\n            result,\n        )\n\n    @classmethod\n    def fetch_company_jobs(cls, company_subdomain):\n        company_subdomain = extract_bamboohr_company_subdomain(\n            company_subdomain\n        )\n\n        cached = cls.cache_get(\n            cls._listing_cache,\n            company_subdomain,\n        )\n\n        if cached is not None:\n            print(\n                "BAMBOOHR LIST CACHE | "\n                f"Company: {company_subdomain} | "\n                f"Jobs: {len(cached)}"\n            )\n            return cached\n\n        payload = fetch_json(\n            (\n                f"{cls.company_base_url(company_subdomain)}"\n                "/careers/list"\n            ),\n            timeout=30,\n        )\n\n        if not isinstance(payload, dict):\n            raise RuntimeError(\n                "BambooHR returned an unexpected careers-list response."\n            )\n\n        jobs = payload.get("result")\n\n        if not isinstance(jobs, list):\n            raise RuntimeError(\n                "BambooHR returned invalid careers-list job data."\n            )\n\n        print(\n            "BAMBOOHR LIST | "\n            f"Company: {company_subdomain} | "\n            f"Jobs: {len(jobs)}"\n        )\n\n        return cls.cache_set(\n            cls._listing_cache,\n            company_subdomain,\n            jobs,\n        )\n\n    @classmethod\n    def fetch_job_detail(\n        cls,\n        company_subdomain,\n        job_id,\n    ):\n        company_subdomain = extract_bamboohr_company_subdomain(\n            company_subdomain\n        )\n        job_id = str(job_id or "").strip()\n\n        if not job_id:\n            raise ValueError("A BambooHR job ID is required.")\n\n        cache_key = (\n            company_subdomain,\n            job_id,\n        )\n\n        cached = cls.cache_get(\n            cls._detail_cache,\n            cache_key,\n        )\n\n        if cached is not None:\n            return cached\n\n        payload = fetch_json(\n            (\n                f"{cls.company_base_url(company_subdomain)}"\n                f"/careers/{job_id}/detail"\n            ),\n            timeout=30,\n        )\n\n        if not isinstance(payload, dict):\n            raise RuntimeError(\n                "BambooHR returned an unexpected "\n                f"detail response for job {job_id}."\n            )\n\n        result = payload.get("result")\n\n        if not isinstance(result, dict):\n            raise RuntimeError(\n                "BambooHR returned invalid detail data "\n                f"for job {job_id}."\n            )\n\n        job = result.get("jobOpening")\n\n        if not isinstance(job, dict):\n            raise RuntimeError(\n                "BambooHR detail response did not contain "\n                f"a jobOpening object for job {job_id}."\n            )\n\n        return cls.cache_set(\n            cls._detail_cache,\n            cache_key,\n            job,\n        )\n\n    @staticmethod\n    def normalized_text(value):\n        return re.sub(\n            r"\\s+",\n            " ",\n            str(value or ""),\n        ).strip()\n\n    @classmethod\n    def normalize_employment_type(cls, *values):\n        text = " ".join(\n            cls.normalized_text(value)\n            for value in values\n            if cls.normalized_text(value)\n        ).casefold()\n\n        if not text:\n            return None\n\n        if "intern" in text:\n            return "Internship"\n\n        if (\n            "part-time" in text\n            or "part time" in text\n            or "parttime" in text\n        ):\n            return "Part-time"\n\n        if "contract" in text:\n            return "Contract"\n\n        if (\n            "temporary" in text\n            or "seasonal" in text\n            or re.search(\n                r"(?<!\\w)temp(?!\\w)",\n                text,\n            )\n        ):\n            return "Temporary"\n\n        if (\n            "full-time" in text\n            or "full time" in text\n            or "fulltime" in text\n        ):\n            return "Full-time"\n\n        return None\n\n    @classmethod\n    def normalize_experience_level(cls, value):\n        text = cls.normalized_text(value).casefold()\n\n        if not text:\n            return None\n\n        if (\n            "intern" in text\n            or "student" in text\n        ):\n            return "intern"\n\n        if (\n            "entry" in text\n            or "new grad" in text\n            or "graduate" in text\n        ):\n            return "entry"\n\n        if "junior" in text:\n            return "junior"\n\n        if (\n            "mid-level" in text\n            or "mid level" in text\n            or "intermediate" in text\n        ):\n            return "mid"\n\n        if (\n            "manager" in text\n            or "supervisor" in text\n            or "executive" in text\n            or "director" in text\n        ):\n            return "manager"\n\n        # BambooHR\'s generic "Experienced" value is not forced into\n        # mid/senior. The shared matcher can infer explicit years\n        # from the full description instead.\n        return None\n\n    @classmethod\n    def normalize_location_type(\n        cls,\n        value,\n        title=None,\n        is_remote=None,\n    ):\n        try:\n            number = int(value)\n        except (\n            TypeError,\n            ValueError,\n        ):\n            number = None\n\n        if number == 0:\n            return "On-site"\n\n        if number == 1:\n            return "Remote"\n\n        if number == 2:\n            return "Hybrid"\n\n        if is_remote is True:\n            return "Remote"\n\n        title_text = cls.normalized_text(title).casefold()\n\n        if "hybrid" in title_text:\n            return "Hybrid"\n\n        if "remote" in title_text:\n            return "Remote"\n\n        return "On-site"\n\n    @classmethod\n    def location_parts(cls, value):\n        if not isinstance(value, dict):\n            return []\n\n        parts = []\n\n        for key in (\n            "city",\n            "state",\n            "country",\n            "addressCountry",\n        ):\n            item = cls.normalized_text(\n                value.get(key)\n            )\n\n            if (\n                item\n                and item not in parts\n            ):\n                parts.append(item)\n\n        return parts\n\n    @classmethod\n    def physical_location(cls, job):\n        primary = cls.location_parts(\n            job.get("location")\n        )\n\n        if primary:\n            return ", ".join(primary)\n\n        ats = cls.location_parts(\n            job.get("atsLocation")\n        )\n\n        if ats:\n            return ", ".join(ats)\n\n        return None\n\n    @classmethod\n    def location_metadata(\n        cls,\n        job,\n        workplace_type,\n    ):\n        if workplace_type == "Remote":\n            return {\n                "location": "Remote",\n                "location_source": "bamboohr_location_type",\n                "location_confidence": 0.4,\n                "remote_candidate_scope": None,\n                "remote_allowed_locations": [],\n                "is_remote": True,\n            }\n\n        location = cls.physical_location(job)\n\n        return {\n            "location": location or "Unknown",\n            "location_source": (\n                "bamboohr_location"\n                if location\n                else "unknown"\n            ),\n            "location_confidence": (\n                1.0\n                if location\n                else 0.0\n            ),\n            "remote_candidate_scope": None,\n            "remote_allowed_locations": [],\n            "is_remote": (\n                workplace_type\n                in {\n                    "Remote",\n                    "Hybrid",\n                }\n            ),\n        }\n\n    @classmethod\n    def posting_url(\n        cls,\n        company_subdomain,\n        job_id,\n        job=None,\n    ):\n        if isinstance(job, dict):\n            share_url = cls.normalized_text(\n                job.get("jobOpeningShareUrl")\n            )\n\n            if share_url:\n                return share_url\n\n        return (\n            f"{cls.company_base_url(company_subdomain)}"\n            f"/careers/{job_id}"\n        )\n\n    @classmethod\n    def normalize_listing_job(\n        cls,\n        raw_job,\n        company_name,\n        company_subdomain,\n    ):\n        if not isinstance(raw_job, dict):\n            return None\n\n        raw_id = raw_job.get("id")\n\n        if raw_id is None:\n            return None\n\n        job_id = str(raw_id).strip()\n        title = cls.normalized_text(\n            raw_job.get("jobOpeningName")\n        )\n\n        if not title:\n            return None\n\n        workplace_type = cls.normalize_location_type(\n            raw_job.get("locationType"),\n            title=title,\n            is_remote=raw_job.get("isRemote"),\n        )\n\n        location_data = cls.location_metadata(\n            raw_job,\n            workplace_type,\n        )\n\n        posting_url = cls.posting_url(\n            company_subdomain,\n            job_id,\n            raw_job,\n        )\n\n        department = cls.normalized_text(\n            raw_job.get("departmentLabel")\n        )\n\n        return {\n            "source": cls.source_name,\n            "external_id": (\n                f"{company_subdomain}:{job_id}"\n            ),\n            "company_name": company_name,\n            "position_title": title,\n            "location": location_data["location"],\n            "location_source": location_data["location_source"],\n            "location_confidence": location_data["location_confidence"],\n            "employment_type": cls.normalize_employment_type(\n                raw_job.get("employmentStatusLabel"),\n                raw_job.get("employmentType"),\n            ),\n            "salary": None,\n            "visa_sponsorship": "Unknown",\n            "overseas_applicant_status": "Unknown",\n            "posting_url": posting_url,\n            "apply_url": posting_url,\n            "job_description": None,\n            "departments": [department] if department else [],\n            "offices": [],\n            "is_remote": location_data["is_remote"],\n            "workplace_type": workplace_type,\n            "remote_candidate_scope": (\n                location_data["remote_candidate_scope"]\n            ),\n            "remote_allowed_locations": (\n                location_data["remote_allowed_locations"]\n            ),\n            "published_at": None,\n            "experience_level": None,\n            "seniority_level": None,\n            "recruiter_name": None,\n            "recruiter_email": None,\n            "recruiter_contact_url": None,\n            "recruiter_contact_source": None,\n        }\n\n    @classmethod\n    def normalize_detail_job(\n        cls,\n        detail,\n        listing_job,\n        company_name,\n        company_subdomain,\n        job_id,\n    ):\n        if not isinstance(detail, dict):\n            return None\n\n        title = (\n            cls.normalized_text(\n                detail.get("jobOpeningName")\n            )\n            or listing_job.get("position_title")\n        )\n\n        if not title:\n            return None\n\n        workplace_type = cls.normalize_location_type(\n            detail.get("locationType"),\n            title=title,\n        )\n\n        location_data = cls.location_metadata(\n            detail,\n            workplace_type,\n        )\n\n        description = clean_html_text(\n            detail.get("description")\n        )\n\n        experience_level = (\n            cls.normalize_experience_level(\n                detail.get("minimumExperience")\n            )\n        )\n\n        posting_url = cls.posting_url(\n            company_subdomain,\n            job_id,\n            detail,\n        )\n\n        department = cls.normalized_text(\n            detail.get("departmentLabel")\n        )\n\n        return {\n            "source": cls.source_name,\n            "external_id": (\n                f"{company_subdomain}:{job_id}"\n            ),\n            "company_name": company_name,\n            "position_title": title,\n            "location": location_data["location"],\n            "location_source": location_data["location_source"],\n            "location_confidence": location_data["location_confidence"],\n            "employment_type": (\n                cls.normalize_employment_type(\n                    detail.get("employmentStatusLabel"),\n                    detail.get("employmentType"),\n                )\n                or listing_job.get("employment_type")\n            ),\n            "salary": (\n                cls.normalized_text(\n                    detail.get("compensation")\n                )\n                or None\n            ),\n            "visa_sponsorship": "Unknown",\n            "overseas_applicant_status": "Unknown",\n            "posting_url": posting_url,\n            "apply_url": posting_url,\n            "job_description": description,\n            "departments": [department] if department else [],\n            "offices": [],\n            "is_remote": location_data["is_remote"],\n            "workplace_type": workplace_type,\n            "remote_candidate_scope": (\n                location_data["remote_candidate_scope"]\n            ),\n            "remote_allowed_locations": (\n                location_data["remote_allowed_locations"]\n            ),\n            "published_at": detail.get("datePosted"),\n            "experience_level": experience_level,\n            "seniority_level": experience_level,\n            "recruiter_name": None,\n            "recruiter_email": None,\n            "recruiter_contact_url": None,\n            "recruiter_contact_source": None,\n        }\n\n    def fetch_validation_jobs(\n        self,\n        company_subdomain,\n    ):\n        company_subdomain = extract_bamboohr_company_subdomain(\n            company_subdomain\n        )\n\n        company_info = self.fetch_company_info(\n            company_subdomain\n        )\n\n        company_name = (\n            self.normalized_text(\n                company_info.get("name")\n            )\n            or company_subdomain\n        )\n\n        jobs = []\n\n        for raw_job in self.fetch_company_jobs(\n            company_subdomain\n        ):\n            job = self.normalize_listing_job(\n                raw_job,\n                company_name,\n                company_subdomain,\n            )\n\n            if job is not None:\n                jobs.append(job)\n\n        return jobs\n\n    def search_company(\n        self,\n        profile,\n        company_subdomain,\n        company_name,\n    ):\n        company_subdomain = extract_bamboohr_company_subdomain(\n            company_subdomain\n        )\n\n        if not company_name or not str(\n            company_name\n        ).strip():\n            raise ValueError(\n                "A company name is required."\n            )\n\n        company_name = str(\n            company_name\n        ).strip()\n\n        listing_pairs = []\n\n        for raw_job in self.fetch_company_jobs(\n            company_subdomain\n        ):\n            normalized = self.normalize_listing_job(\n                raw_job,\n                company_name,\n                company_subdomain,\n            )\n\n            if normalized is not None:\n                listing_pairs.append(\n                    (\n                        raw_job,\n                        normalized,\n                    )\n                )\n\n        role_candidates = [\n            (\n                raw_job,\n                listing_job,\n            )\n            for (\n                raw_job,\n                listing_job,\n            )\n            in listing_pairs\n            if matches_role_title(\n                listing_job,\n                profile,\n            )\n        ]\n\n        print(\n            "BAMBOOHR PRE-DETAIL FILTER | "\n            f"Company: {company_subdomain} | "\n            f"Listings: {len(listing_pairs)} | "\n            f"Role candidates: {len(role_candidates)}"\n        )\n\n        normalized_details = []\n        detail_errors = 0\n\n        for (\n            raw_job,\n            listing_job,\n        ) in role_candidates:\n            raw_id = raw_job.get("id")\n\n            if raw_id is None:\n                continue\n\n            job_id = str(raw_id).strip()\n\n            try:\n                detail = self.fetch_job_detail(\n                    company_subdomain,\n                    job_id,\n                )\n\n                job = self.normalize_detail_job(\n                    detail,\n                    listing_job,\n                    company_name,\n                    company_subdomain,\n                    job_id,\n                )\n\n            except Exception as error:\n                detail_errors += 1\n\n                print(\n                    "BAMBOOHR DETAIL FAILED | "\n                    f"Company: {company_subdomain} | "\n                    f"Job: {job_id} | "\n                    f"Error: {error}"\n                )\n                continue\n\n            if (\n                job is not None\n                and job.get("posting_url")\n            ):\n                normalized_details.append(job)\n\n        if (\n            role_candidates\n            and not normalized_details\n            and detail_errors\n            == len(role_candidates)\n        ):\n            raise RuntimeError(\n                "BambooHR detail requests failed "\n                "for every role candidate."\n            )\n\n        matched_jobs = [\n            job\n            for job in normalized_details\n            if job_matches_profile(\n                job,\n                profile,\n            )\n        ]\n\n        print(\n            "BAMBOOHR SEARCH COMPLETE | "\n            f"Company: {company_subdomain} | "\n            f"Listings: {len(listing_pairs)} | "\n            f"Role candidates: {len(role_candidates)} | "\n            f"Details normalized: {len(normalized_details)} | "\n            f"Detail errors: {detail_errors} | "\n            f"Matched: {len(matched_jobs)}"\n        )\n\n        return matched_jobs\n\n    def search(\n        self,\n        profile,\n        source_config=None,\n    ):\n        if source_config is None:\n            raise ValueError(\n                "BambooHR requires a company "\n                "source configuration."\n            )\n\n        return self.search_company(\n            profile=profile,\n            company_subdomain=(\n                source_config.source_identifier\n            ),\n            company_name=(\n                source_config.company_name\n            ),\n        )\n'
BAMBOOHR_EXTRACTOR = '\n\ndef extract_bamboohr_company_subdomain(value):\n    if not value or not str(value).strip():\n        raise ValueError(\n            "A BambooHR careers URL or company subdomain is required."\n        )\n\n    cleaned_value = str(value).strip()\n\n    if "://" not in cleaned_value:\n        identifier = cleaned_value.strip("/").lower()\n\n        if "/" in identifier:\n            raise ValueError(\n                "A BambooHR company subdomain must not contain a path."\n            )\n\n    else:\n        parsed_url = urlparse(cleaned_value)\n        hostname = (\n            parsed_url.hostname\n            or ""\n        ).lower()\n\n        suffix = ".bamboohr.com"\n\n        if (\n            not hostname.endswith(suffix)\n            or hostname == "bamboohr.com"\n        ):\n            raise ValueError(\n                "This does not appear to be a BambooHR careers URL."\n            )\n\n        identifier = hostname[\n            :-len(suffix)\n        ]\n\n    if (\n        not identifier\n        or "." in identifier\n        or identifier\n        in BAMBOOHR_RESERVED_SUBDOMAINS\n    ):\n        raise ValueError(\n            "The BambooHR URL does not contain a usable company subdomain."\n        )\n\n    if not all(\n        character.isalnum()\n        or character in "-_"\n        for character in identifier\n    ):\n        raise ValueError(\n            "The BambooHR company subdomain contains unsupported characters."\n        )\n\n    return identifier\n'
BAMBOOHR_CRAWL_BLOCK = '    if hostname.endswith(\n        ".bamboohr.com"\n    ):\n        try:\n            board_identifier = (\n                extract_bamboohr_company_subdomain(\n                    url\n                )\n            )\n        except (\n            TypeError,\n            ValueError,\n        ):\n            return None\n\n        normalized_url = (\n            f"https://{board_identifier}"\n            ".bamboohr.com/careers"\n        )\n\n        return {\n            "source_type": "bamboohr",\n            "source_identifier": (\n                board_identifier\n            ),\n            "url": normalized_url,\n            "key": (\n                "bamboohr",\n                board_identifier.lower(),\n            ),\n        }\n\n'


def fail(message):
    raise RuntimeError(message)


def require_file(path):
    if not path.is_file():
        fail(
            f"Required file was not found: {path}\n"
            "Run this installer from the get-a-job project root."
        )


def compile_python(text, filename):
    try:
        compile(text, str(filename), "exec")
    except SyntaxError as error:
        fail(
            "Python validation failed for "
            f"{filename}:\n{error}"
        )


def replace_once(text, old, new, description):
    if new in text:
        print(f"ALREADY INSTALLED | {description}")
        return text

    count = text.count(old)

    if count != 1:
        fail(
            f"Could not safely patch {description}.\n"
            f"Expected exactly 1 anchor match, found {count}."
        )

    print(f"PATCHING | {description}")
    return text.replace(old, new, 1)


def write_if_changed(path, original, patched):
    compile_python(patched, path)

    if patched != original:
        path.write_text(
            patched,
            encoding="utf-8",
        )
        return True

    return False


def install_source():
    if SOURCE_PATH.exists():
        existing = SOURCE_PATH.read_text(
            encoding="utf-8"
        )

        if existing == BAMBOOHR_SOURCE:
            print(
                "ALREADY INSTALLED | BambooHR source file"
            )
            return False

        if "class BambooHRJobSource" not in existing:
            fail(
                f"{SOURCE_PATH} already exists but does not look "
                "like the expected BambooHR source. It was left untouched."
            )

        print("UPDATING | Existing BambooHR source file")
    else:
        print("CREATING | services/job_sources/bamboohr.py")

    compile_python(
        BAMBOOHR_SOURCE,
        SOURCE_PATH,
    )

    SOURCE_PATH.write_text(
        BAMBOOHR_SOURCE,
        encoding="utf-8",
    )

    return True


def patch_registry():
    original = REGISTRY_PATH.read_text(
        encoding="utf-8"
    )

    patched = replace_once(
        original,
        "from services.job_sources.green_japan import GreenJapanJobSource\n",
        (
            "from services.job_sources.green_japan import GreenJapanJobSource\n"
            "from services.job_sources.bamboohr import BambooHRJobSource\n"
        ),
        "BambooHR registry import",
    )

    patched = replace_once(
        patched,
        '    "green_japan": GreenJapanJobSource,\n}',
        (
            '    "green_japan": GreenJapanJobSource,\n'
            '    "bamboohr": BambooHRJobSource,\n'
            '}'
        ),
        "BambooHR registry entry",
    )

    return write_if_changed(
        REGISTRY_PATH,
        original,
        patched,
    )


def patch_source_utils():
    original = SOURCE_UTILS_PATH.read_text(
        encoding="utf-8"
    )

    hosts_anchor = (
        'ASHBY_HOSTS = {\n'
        '    "jobs.ashbyhq.com"\n'
        '}\n'
    )

    hosts_replacement = (
        hosts_anchor
        + '\nBAMBOOHR_RESERVED_SUBDOMAINS = {\n'
        '    "api",\n'
        '    "documentation",\n'
        '    "help",\n'
        '    "static",\n'
        '    "www",\n'
        '}\n'
    )

    patched = replace_once(
        original,
        hosts_anchor,
        hosts_replacement,
        "BambooHR source-utils constants",
    )

    ashby_anchor = (
        "\n\ndef extract_ashby_job_board_name(value):\n"
    )

    patched = replace_once(
        patched,
        ashby_anchor,
        BAMBOOHR_EXTRACTOR + ashby_anchor,
        "BambooHR company-subdomain extractor",
    )

    return write_if_changed(
        SOURCE_UTILS_PATH,
        original,
        patched,
    )


def patch_discovery():
    original = DISCOVERY_PATH.read_text(
        encoding="utf-8"
    )

    patched = replace_once(
        original,
        (
            "    extract_ashby_job_board_name,\n"
            "    extract_greenhouse_board_token,\n"
            "    extract_lever_company_slug\n"
            ")"
        ),
        (
            "    extract_ashby_job_board_name,\n"
            "    extract_greenhouse_board_token,\n"
            "    extract_lever_company_slug,\n"
            "    extract_bamboohr_company_subdomain,\n"
            ")"
        ),
        "BambooHR discovery import",
    )

    anchor = (
        '    if hostname.endswith(\n'
        '        ".recruitee.com"\n'
        '    ):\n'
        '        return (\n'
        '            "recruitee",\n'
        '            RecruiteeJobSource.extract_company_slug(\n'
        '                cleaned_url\n'
        '            )\n'
        '        )\n'
        '\n'
        '    raise ValueError(\n'
    )

    replacement = (
        '    if hostname.endswith(\n'
        '        ".recruitee.com"\n'
        '    ):\n'
        '        return (\n'
        '            "recruitee",\n'
        '            RecruiteeJobSource.extract_company_slug(\n'
        '                cleaned_url\n'
        '            )\n'
        '        )\n'
        '\n'
        '    if hostname.endswith(\n'
        '        ".bamboohr.com"\n'
        '    ):\n'
        '        return (\n'
        '            "bamboohr",\n'
        '            extract_bamboohr_company_subdomain(\n'
        '                cleaned_url\n'
        '            )\n'
        '        )\n'
        '\n'
        '    raise ValueError(\n'
    )

    patched = replace_once(
        patched,
        anchor,
        replacement,
        "BambooHR URL detection",
    )

    patched = replace_once(
        patched,
        (
            '"Currently supported: Greenhouse, Lever, '
            'Ashby, Workday, and Recruitee."'
        ),
        (
            '"Currently supported: Greenhouse, Lever, '
            'Ashby, Workday, Recruitee, and BambooHR."'
        ),
        "BambooHR discovery message",
    )

    return write_if_changed(
        DISCOVERY_PATH,
        original,
        patched,
    )


def patch_common_crawl():
    original = COMMON_CRAWL_PATH.read_text(
        encoding="utf-8"
    )

    patched = replace_once(
        original,
        (
            "from services.job_sources.recruitee "
            "import RecruiteeJobSource\n"
        ),
        (
            "from services.job_sources.recruitee "
            "import RecruiteeJobSource\n"
            "from services.job_sources.source_utils "
            "import extract_bamboohr_company_subdomain\n"
        ),
        "BambooHR Common Crawl import",
    )

    patched = replace_once(
        patched,
        (
            '    "recruitee": (\n'
            '        "*.recruitee.com/o/*",\n'
            '    ),\n'
            '}'
        ),
        (
            '    "recruitee": (\n'
            '        "*.recruitee.com/o/*",\n'
            '    ),\n'
            '    "bamboohr": (\n'
            '        "*.bamboohr.com/careers*",\n'
            '    ),\n'
            '}'
        ),
        "BambooHR Common Crawl pattern",
    )

    recruitee_anchor = (
        '    if hostname.endswith(\n'
        '        ".recruitee.com"\n'
        '    ):\n'
    )

    patched = replace_once(
        patched,
        recruitee_anchor,
        BAMBOOHR_CRAWL_BLOCK + recruitee_anchor,
        "BambooHR Common Crawl normalization",
    )

    return write_if_changed(
        COMMON_CRAWL_PATH,
        original,
        patched,
    )


def patch_forms():
    original = FORMS_PATH.read_text(
        encoding="utf-8"
    )

    patched = replace_once(
        original,
        (
            '            ("ashby", "Ashby"),\n'
            '            ("workday", "Workday")\n'
        ),
        (
            '            ("ashby", "Ashby"),\n'
            '            ("workday", "Workday"),\n'
            '            ("bamboohr", "BambooHR")\n'
        ),
        "BambooHR manual source choice",
    )

    patched = replace_once(
        patched,
        (
            '                "https://jobs.ashbyhq.com/example\\n"\n'
            '                "https://nvidia.wd5.myworkdayjobs.com/"\n'
            '                "NVIDIAExternalCareerSite"\n'
        ),
        (
            '                "https://jobs.ashbyhq.com/example\\n"\n'
            '                "https://nvidia.wd5.myworkdayjobs.com/"\n'
            '                "NVIDIAExternalCareerSite\\n"\n'
            '                "https://soundstripe.bamboohr.com/careers"\n'
        ),
        "BambooHR discovery-form example",
    )

    return write_if_changed(
        FORMS_PATH,
        original,
        patched,
    )


def validate():
    source_text = SOURCE_PATH.read_text(encoding="utf-8")
    registry_text = REGISTRY_PATH.read_text(encoding="utf-8")
    utils_text = SOURCE_UTILS_PATH.read_text(encoding="utf-8")
    discovery_text = DISCOVERY_PATH.read_text(encoding="utf-8")
    crawl_text = COMMON_CRAWL_PATH.read_text(encoding="utf-8")
    forms_text = FORMS_PATH.read_text(encoding="utf-8")

    checks = (
        (
            source_text,
            "class BambooHRJobSource(BaseJobSource):",
            "source class",
        ),
        (
            source_text,
            'source_type = "bamboohr"',
            "source type",
        ),
        (
            source_text,
            "/careers/list",
            "careers-list endpoint",
        ),
        (
            source_text,
            "/careers/{job_id}/detail",
            "detail endpoint",
        ),
        (
            registry_text,
            '"bamboohr": BambooHRJobSource,',
            "registry entry",
        ),
        (
            utils_text,
            "def extract_bamboohr_company_subdomain",
            "company subdomain extractor",
        ),
        (
            discovery_text,
            '"bamboohr",',
            "manual URL discovery support",
        ),
        (
            crawl_text,
            '"bamboohr": (',
            "automatic discovery pattern",
        ),
        (
            forms_text,
            '("bamboohr", "BambooHR")',
            "manual form source option",
        ),
    )

    for text, fragment, label in checks:
        if fragment not in text:
            fail(
                "Post-install validation failed: "
                f"missing {label}."
            )

    for path, text in (
        (SOURCE_PATH, source_text),
        (REGISTRY_PATH, registry_text),
        (SOURCE_UTILS_PATH, utils_text),
        (DISCOVERY_PATH, discovery_text),
        (COMMON_CRAWL_PATH, crawl_text),
        (FORMS_PATH, forms_text),
    ):
        compile_python(text, path)


def main():
    print("=" * 76)
    print("JOB AD INFINITUM - BAMBOOHR SOURCE INSTALLER")
    print("=" * 76)
    print(f"Project root: {ROOT}")
    print()

    for required in (
        ROOT / "app.py",
        ROOT / "models.py",
        SOURCE_PATH.parent / "base.py",
        SOURCE_PATH.parent / "http_client.py",
        SOURCE_PATH.parent / "job_match_service.py",
        REGISTRY_PATH,
        SOURCE_UTILS_PATH,
        DISCOVERY_PATH,
        COMMON_CRAWL_PATH,
        FORMS_PATH,
    ):
        require_file(required)

    source_changed = install_source()
    registry_changed = patch_registry()
    utils_changed = patch_source_utils()
    discovery_changed = patch_discovery()
    crawl_changed = patch_common_crawl()
    forms_changed = patch_forms()

    validate()

    print()
    print("=" * 76)
    print("BAMBOOHR INSTALL COMPLETE")
    print("=" * 76)
    print(
        "Source file: "
        + ("created/updated" if source_changed else "already correct")
    )
    print(
        "Registry: "
        + ("updated" if registry_changed else "already correct")
    )
    print(
        "Source URL parsing: "
        + ("updated" if utils_changed else "already correct")
    )
    print(
        "Manual source discovery: "
        + ("updated" if discovery_changed else "already correct")
    )
    print(
        "Automatic Common Crawl discovery: "
        + ("updated" if crawl_changed else "already correct")
    )
    print(
        "Source form: "
        + ("updated" if forms_changed else "already correct")
    )
    print()
    print("Configured ATS source: yes")
    print("Database migration required: no")
    print("Global scheduler list change required: no")
    print("Public careers list endpoint: enabled")
    print("Public job-detail endpoint: enabled")
    print("Pre-detail tech-role filtering: enabled")
    print("Shared list/detail cache: 30 minutes")
    print("BambooHR locationType 0/1/2 normalization: enabled")
    print("Compensation/date/description normalization: enabled")
    print("Manual + automatic URL discovery: enabled")
    print()
    print("Python syntax validation: PASSED")
    print("Post-install checks: PASSED")
    print("No backup files were created.")
    print()
    print(
        "Next: run the installer, then discover/add a BambooHR "
        "company and run the normal search."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print()
        print("=" * 76)
        print("INSTALL FAILED")
        print("=" * 76)
        print(error)
        sys.exit(1)