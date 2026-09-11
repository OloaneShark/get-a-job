import re
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit


EXECUTOR_CHROME_AGENT = "chrome_agent"
EXECUTOR_LEGACY = "legacy_submission"


CHROME_AGENT_HOSTS = {
    "jobs.lever.co",
    "jobs.eu.lever.co",
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "job-boards.eu.greenhouse.io",
    "grnh.se",
    "himalayas.app",
    "www.himalayas.app",
    "remotefirstjobs.com",
    "www.remotefirstjobs.com",
    "japan-dev.com",
    "www.japan-dev.com",
    "weworkremotely.com",
    "www.weworkremotely.com",
    "jooble.org",
    "www.jooble.org",
    "remoteok.com",
    "www.remoteok.com",
    "jobicy.com",
    "www.jobicy.com",
    "tokyodev.com",
    "www.tokyodev.com",
    "adzuna.com",
    "www.adzuna.com",
    "adzuna.com.au",
    "www.adzuna.com.au",
    "adzuna.at",
    "www.adzuna.at",
    "adzuna.be",
    "www.adzuna.be",
    "adzuna.com.br",
    "www.adzuna.com.br",
    "adzuna.ca",
    "www.adzuna.ca",
    "adzuna.fr",
    "www.adzuna.fr",
    "adzuna.de",
    "www.adzuna.de",
    "adzuna.in",
    "www.adzuna.in",
    "adzuna.it",
    "www.adzuna.it",
    "adzuna.com.mx",
    "www.adzuna.com.mx",
    "adzuna.nl",
    "www.adzuna.nl",
    "adzuna.co.nz",
    "www.adzuna.co.nz",
    "adzuna.pl",
    "www.adzuna.pl",
    "adzuna.sg",
    "www.adzuna.sg",
    "adzuna.co.za",
    "www.adzuna.co.za",
    "adzuna.es",
    "www.adzuna.es",
    "adzuna.ch",
    "www.adzuna.ch",
    "adzuna.co.uk",
    "www.adzuna.co.uk",
    "themuse.com",
    "www.themuse.com",
    "jobs.ashbyhq.com",
}

GREENHOUSE_BOARD_QUERY_KEYS = (
    "for",
    "gh_board",
    "board",
    "board_token",
)

NON_EMPLOYER_APPLICATION_HOSTS = {
    "127.0.0.1",
    "localhost",
    "jobfinitum.com",
    "www.jobfinitum.com",
}

RESOLVER_SOURCE_HOSTS = {
    host
    for host in CHROME_AGENT_HOSTS
    if host not in {
        "jobs.lever.co",
        "jobs.eu.lever.co",
        "boards.greenhouse.io",
        "boards.eu.greenhouse.io",
        "job-boards.greenhouse.io",
        "job-boards.eu.greenhouse.io",
        "grnh.se",
        "jobs.ashbyhq.com",
    }
}

# These are real application systems, not wrappers around one of the
# currently supported hosted ATS forms. Sending them through the generic
# wrapper scanner only adds a delay before the inevitable manual handoff.
UNSUPPORTED_ATS_HOST_SUFFIXES = (
    "adp.com",
    "applytojob.com",
    "avature.net",
    "bamboohr.com",
    "careers-page.com",
    "careerswift.ai",
    "dayforcehcm.com",
    "dover.com",
    "gupy.io",
    "icims.com",
    "jobvite.com",
    "myworkdayjobs.com",
    "oraclecloud.com",
    "paylocity.com",
    "pinpointhq.com",
    "python.org",
    "recruitee.com",
    "rippling.com",
    "smartrecruiters.com",
    "successfactors.com",
    "teamtailor.com",
    "trakstar.com",
    "ultipro.com",
    "workable.com",
    "zoho.com",
    "zohorecruit.com",
    "zohorecruit.com.au",
)


def _host_matches_suffix(host, suffixes):
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in suffixes
    )


def _supported_wrapper_url_hint(parsed):
    query = parse_qs(
        parsed.query,
        keep_blank_values=False,
    )
    greenhouse_job_id = str(
        (query.get("gh_jid") or [""])[0]
    ).strip()

    if re.fullmatch(r"\d+", greenhouse_job_id):
        return True

    normalized = urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.query,
            "",
        )
    ).lower()

    return any(
        marker in normalized
        for marker in (
            "greenhouse.io",
            "boards-api.greenhouse.io",
            "lever.co",
            "ashbyhq.com",
        )
    )


def _came_from_supported_resolver(job, target_host):
    posting_url = str(
        getattr(job, "posting_url", "") or ""
    ).strip()

    try:
        posting = urlsplit(posting_url)
    except ValueError:
        return False

    posting_host = (posting.hostname or "").lower()

    return (
        posting.scheme == "https"
        and posting_host in RESOLVER_SOURCE_HOSTS
        and posting_host != target_host
    )


def embedded_greenhouse_application_target(job):
    raw_target = str(
        job.apply_url
        or job.posting_url
        or ""
    ).strip()

    try:
        parsed = urlsplit(raw_target)
    except ValueError:
        return None

    query = parse_qs(
        parsed.query,
        keep_blank_values=False,
    )
    job_id = str(
        (query.get("gh_jid") or [""])[0]
    ).strip()

    if not re.fullmatch(r"\d+", job_id):
        return None

    board_token = ""

    for key in GREENHOUSE_BOARD_QUERY_KEYS:
        candidate = str(
            (query.get(key) or [""])[0]
        ).strip()

        if re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
            board_token = candidate
            break

    if not board_token:
        return None

    return urlunsplit(
        (
            "https",
            "job-boards.greenhouse.io",
            "/embed/job_app",
            urlencode(
                {
                    "for": board_token,
                    "token": job_id,
                }
            ),
            "",
        )
    )


def application_target(job):
    raw_target = str(
        job.apply_url
        or job.posting_url
        or ""
    ).strip()

    return (
        embedded_greenhouse_application_target(job)
        or raw_target
    )


def application_host(job):
    target = application_target(job)

    return (
        urlsplit(target).hostname
        or ""
    ).lower()


def browser_resolvable_application(job):
    try:
        parsed = urlsplit(application_target(job))
    except ValueError:
        return False

    host = (parsed.hostname or "").lower()

    if (
        parsed.scheme != "https"
        or not host
        or host in NON_EMPLOYER_APPLICATION_HOSTS
        or _host_matches_suffix(
            host,
            UNSUPPORTED_ATS_HOST_SUFFIXES,
        )
    ):
        return False

    return (
        _supported_wrapper_url_hint(parsed)
        or _came_from_supported_resolver(job, host)
    )


def get_submission_executor(job):
    # Central execution routing for Auto Apply.
    # ATS hosts are migrated into the Chrome Agent
    # framework here as their adapters become ready.
    host = application_host(job)

    if (
        host in CHROME_AGENT_HOSTS
        or browser_resolvable_application(job)
    ):
        return EXECUTOR_CHROME_AGENT

    return EXECUTOR_LEGACY


def uses_chrome_agent(job):
    return (
        get_submission_executor(job)
        == EXECUTOR_CHROME_AGENT
    )
