import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from types import SimpleNamespace

from models import (
    CachedSourceJob,
    JobSourceCacheState,
)
from services.job_sources.job_match_service import (
    job_matches_profile,
    matches_role_title,
)
from services.job_sources.registry import create_source
from services.job_sources.shared_job_cache import (
    cache_key_for_job,
    restore_json,
    state_snapshot,
    utc_now,
)
from services.job_sources.workday_crawler import (
    WorkdayCrawler,
)


CONFIGURED_SOURCE_REFRESH_INTERVAL = timedelta(
    hours=6
)
CONFIGURED_SOURCE_REFRESH_WORKERS = 4

GENERIC_CONFIGURED_CACHE_SCHEMA = (
    "configured-tech-inventory-v1"
)
WORKDAY_CONFIGURED_CACHE_SCHEMA = (
    "configured-workday-profile-union-v1"
)

MAX_WORKDAY_SHARED_SEARCH_TERMS = 32
MAX_WORKDAY_SHARED_DETAIL_CANDIDATES = 1200


TECH_INVENTORY_KEYWORDS = (
    "software engineer",
    "software developer",
    "full stack",
    "frontend",
    "backend",
    "devops",
    "devsecops",
    "cloud engineer",
    "security engineer",
    "application security",
    "cybersecurity",
    "site reliability",
    "sre",
    "platform engineer",
    "qa engineer",
    "quality assurance engineer",
    "data engineer",
    "machine learning engineer",
    "mobile developer",
    "web developer",
    "IT support",
    "IT specialist",
    "IT technician",
    "help desk",
    "service desk",
    "administrator",
    "systems",
)


def normalized_text(value):
    return str(
        value or ""
    ).strip()


def configured_cache_namespace(
    source_config,
):
    source_type = normalized_text(
        getattr(
            source_config,
            "source_type",
            "",
        )
    ).lower()

    source_id = getattr(
        source_config,
        "id",
        None,
    )

    if (
        not source_type
        or source_id is None
    ):
        raise ValueError(
            "Configured source cache requires "
            "a source type and database ID."
        )

    namespace = (
        f"configured:{source_type}:{source_id}"
    )

    if len(namespace) > 80:
        raise ValueError(
            "Configured source cache namespace "
            "exceeds the database limit."
        )

    return namespace


def configured_cache_signature(
    source_config,
    profile_signature,
):
    source_type = normalized_text(
        getattr(
            source_config,
            "source_type",
            "",
        )
    ).lower()

    if source_type == "workday":
        raw_value = (
            WORKDAY_CONFIGURED_CACHE_SCHEMA
            + ":"
            + normalized_text(
                profile_signature
            )
        )
    else:
        raw_value = (
            GENERIC_CONFIGURED_CACHE_SCHEMA
        )

    return hashlib.sha256(
        raw_value.encode(
            "utf-8",
            errors="replace",
        )
    ).hexdigest()


def technical_inventory_profile():
    return SimpleNamespace(
        id=None,
        user_id=None,
        name=(
            "Shared configured-source "
            "technology inventory"
        ),
        keywords=",".join(
            TECH_INVENTORY_KEYWORDS
        ),
        locations="",
        employment_types="",
        workplace_types=(
            "remote,hybrid,on-site"
        ),
        overseas_applicant_preference=(
            "any"
        ),
        remote_only=False,
        visa_required=False,
        minimum_salary=None,
        search_frequency="manual",
        active=True,
        experience_levels="",
        visa_preference="any",
        remote_scope="any",
        maximum_posting_age_days=60,
    )


def add_cache_metadata(
    job,
    source_config,
):
    output = dict(
        job
    )

    output[
        "_cache_source_type"
    ] = normalized_text(
        getattr(
            source_config,
            "source_type",
            "",
        )
    ).lower()

    output[
        "_cache_source_config_id"
    ] = getattr(
        source_config,
        "id",
        None,
    )

    output[
        "_cache_source_identifier"
    ] = normalized_text(
        getattr(
            source_config,
            "source_identifier",
            "",
        )
    )

    output[
        "_cache_company_name"
    ] = normalized_text(
        getattr(
            source_config,
            "company_name",
            "",
        )
    )

    return output


def deduplicate_jobs(jobs):
    deduplicated = {}

    for job in jobs or []:
        if not isinstance(
            job,
            dict,
        ):
            continue

        external_id = normalized_text(
            job.get(
                "external_id"
            )
        )
        posting_url = normalized_text(
            job.get(
                "posting_url"
            )
        )

        key = (
            external_id
            or posting_url
        )

        if not key:
            continue

        deduplicated[
            key
        ] = job

    return list(
        deduplicated.values()
    )


def generic_configured_inventory(
    source,
    source_config,
):
    profile = (
        technical_inventory_profile()
    )

    jobs = source.search(
        profile=profile,
        source_config=source_config,
    )

    return (
        deduplicate_jobs(
            jobs
        ),
        True,
    )


def workday_search_terms(
    source,
    profiles,
):
    terms = []
    seen = set()

    for profile in profiles:
        try:
            profile_terms = (
                source.build_search_terms(
                    profile
                )
            )
        except Exception:
            continue

        for term in profile_terms:
            normalized = (
                source.normalize_search_phrase(
                    term
                )
            )
            key = normalized.casefold()

            if (
                not normalized
                or key in seen
            ):
                continue

            seen.add(
                key
            )
            terms.append(
                normalized
            )

    if not terms:
        terms = [
            "software engineer",
            "software developer",
            "devops",
            "security engineer",
            "cloud engineer",
            "data engineer",
            "IT support",
        ]

    if (
        len(terms)
        > MAX_WORKDAY_SHARED_SEARCH_TERMS
    ):
        print(
            "WORKDAY SHARED QUERY LIMIT | "
            f"Unique queries: {len(terms)} | "
            f"Using first "
            f"{MAX_WORKDAY_SHARED_SEARCH_TERMS}."
        )

        terms = terms[
            :MAX_WORKDAY_SHARED_SEARCH_TERMS
        ]

    return terms


def workday_role_profiles(
    source,
    summary,
    company_name,
    profiles,
):
    role_job = (
        source.summary_for_role_check(
            summary,
            company_name,
        )
    )

    return [
        profile
        for profile
        in profiles
        if matches_role_title(
            role_job,
            profile,
        )
    ]


def collect_workday_inventory(
    source,
    source_config,
    profiles,
):
    board_url = normalized_text(
        getattr(
            source_config,
            "source_identifier",
            "",
        )
    )

    if not board_url:
        raise ValueError(
            "Workday requires a career-board URL."
        )

    company_name = (
        normalized_text(
            getattr(
                source_config,
                "company_name",
                "",
            )
        )
        or "Unknown Company"
    )

    search_terms = workday_search_terms(
        source,
        profiles,
    )

    print(
        "WORKDAY SHARED BOARD QUERIES | "
        f"Company: {company_name} | "
        f"Queries: {search_terms}"
    )

    summaries = source.fetch_company_jobs(
        board_url,
        search_terms=search_terms,
    )

    role_candidates = []
    experience_candidates = []

    for summary in summaries:
        matching_profiles = (
            workday_role_profiles(
                source,
                summary,
                company_name,
                profiles,
            )
        )

        if not matching_profiles:
            continue

        role_candidates.append(
            summary
        )

        if any(
            source.title_experience_matches_profile(
                summary,
                profile,
            )
            for profile
            in matching_profiles
        ):
            experience_candidates.append(
                summary
            )

    detail_candidates = (
        experience_candidates
    )

    if (
        len(detail_candidates)
        > MAX_WORKDAY_SHARED_DETAIL_CANDIDATES
    ):
        print(
            "WORKDAY SHARED DETAIL LIMIT | "
            f"Company: {company_name} | "
            f"Candidates: "
            f"{len(detail_candidates)} | "
            f"Using first "
            f"{MAX_WORKDAY_SHARED_DETAIL_CANDIDATES}."
        )

        detail_candidates = (
            detail_candidates[
                :MAX_WORKDAY_SHARED_DETAIL_CANDIDATES
            ]
        )

    normalized_jobs = []
    detail_errors = 0

    with ThreadPoolExecutor(
        max_workers=(
            source.max_detail_workers
        )
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
            in detail_candidates
            if summary.get(
                "externalPath"
            )
        }

        for future in as_completed(
            future_map
        ):
            summary = (
                future_map[
                    future
                ]
            )

            try:
                detail_payload = (
                    future.result()
                )

                normalized_job = (
                    source.normalize_detail_job(
                        summary,
                        detail_payload,
                        company_name,
                    )
                )

            except Exception as error:
                detail_errors += 1

                print(
                    "WORKDAY SHARED DETAIL ERROR | "
                    f"Company: {company_name} | "
                    f"URL: "
                    f"{summary.get('posting_url')} | "
                    f"Error: {error}"
                )
                continue

            if normalized_job:
                normalized_jobs.append(
                    normalized_job
                )

    normalized_jobs = deduplicate_jobs(
        normalized_jobs
    )

    print(
        "WORKDAY SHARED BOARD COMPLETE | "
        f"Company: {company_name} | "
        f"Queries: {len(search_terms)} | "
        f"Listings: {len(summaries)} | "
        f"Role candidates: "
        f"{len(role_candidates)} | "
        f"Detail candidates: "
        f"{len(detail_candidates)} | "
        f"Normalized: "
        f"{len(normalized_jobs)} | "
        f"Detail errors: {detail_errors}"
    )

    # Workday is query-driven here. Do not prune older
    # cached rows merely because a later profile-union
    # refresh used a different query set.
    return (
        normalized_jobs,
        False,
    )


def collect_configured_source_inventory(
    profiles,
    source_config,
):
    source_type = normalized_text(
        getattr(
            source_config,
            "source_type",
            "",
        )
    ).lower()

    source = create_source(
        source_type
    )

    company_name = (
        normalized_text(
            getattr(
                source_config,
                "company_name",
                "",
            )
        )
        or "Unknown Company"
    )

    print(
        "CONFIGURED SOURCE REFRESH START | "
        f"Source: {source.source_name} | "
        f"Company: {company_name}"
    )

    if source_type == "workday":
        (
            jobs,
            complete_inventory,
        ) = collect_workday_inventory(
            source,
            source_config,
            profiles,
        )
    else:
        (
            jobs,
            complete_inventory,
        ) = generic_configured_inventory(
            source,
            source_config,
        )

    jobs = [
        add_cache_metadata(
            job,
            source_config,
        )
        for job
        in deduplicate_jobs(
            jobs
        )
    ]

    display_name = (
        f"{source.source_name}: "
        f"{company_name}"
    )[:120]

    print(
        "CONFIGURED SOURCE REFRESH COMPLETE | "
        f"Source: {source.source_name} | "
        f"Company: {company_name} | "
        f"Tech jobs: {len(jobs)}"
    )

    return {
        "source_type": source_type,
        "source_name": (
            source.source_name
        ),
        "display_name": (
            display_name
        ),
        "company_name": (
            company_name
        ),
        "jobs": jobs,
        "complete_inventory": (
            complete_inventory
        ),
    }


def iter_configured_source_refreshes(
    profiles,
    source_configs,
):
    if not source_configs:
        return

    worker_count = min(
        CONFIGURED_SOURCE_REFRESH_WORKERS,
        max(
            1,
            len(source_configs),
        ),
    )

    with ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        future_map = {
            executor.submit(
                collect_configured_source_inventory,
                profiles,
                source_config,
            ): source_config
            for source_config
            in source_configs
        }

        for future in as_completed(
            future_map
        ):
            source_config = (
                future_map[
                    future
                ]
            )

            try:
                result = (
                    future.result()
                )
                error = None

            except Exception as caught:
                result = None
                error = caught

            yield (
                source_config,
                result,
                error,
            )


def load_configured_cache_bundles(
    namespaces,
):
    namespaces = list(
        dict.fromkeys(
            namespaces
        )
    )

    if not namespaces:
        return {}

    now = utc_now()

    states = (
        JobSourceCacheState.query
        .filter(
            JobSourceCacheState
            .source_type
            .in_(namespaces)
        )
        .all()
    )

    rows = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob
            .source_type
            .in_(namespaces),
            CachedSourceJob.expires_at
            > now,
        )
        .all()
    )

    bundles = {
        namespace: {
            "state": None,
            "jobs": [],
        }
        for namespace
        in namespaces
    }

    for state in states:
        namespace = (
            state.source_type
        )

        if namespace in bundles:
            bundles[
                namespace
            ][
                "state"
            ] = state_snapshot(
                state
            )

    for row in rows:
        namespace = (
            row.source_type
        )

        if namespace not in bundles:
            continue

        if not isinstance(
            row.job_payload,
            dict,
        ):
            continue

        bundles[
            namespace
        ][
            "jobs"
        ].append(
            restore_json(
                row.job_payload
            )
        )

    return bundles


def prune_missing_configured_jobs(
    namespace,
    jobs,
):
    keep_keys = {
        cache_key_for_job(
            job
        )
        for job
        in jobs or []
        if cache_key_for_job(
            job
        )
    }

    query = (
        CachedSourceJob.query
        .filter(
            CachedSourceJob.source_type
            == namespace
        )
    )

    if keep_keys:
        rows = (
            query
            .filter(
                ~CachedSourceJob.cache_key
                .in_(keep_keys)
            )
            .all()
        )
    else:
        rows = query.all()

    removed = len(
        rows
    )

    for row in rows:
        from models import db
        db.session.delete(
            row
        )

    return removed
