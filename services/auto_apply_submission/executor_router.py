from urllib.parse import urlsplit


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
    "jobs.ashbyhq.com",
}


def application_target(job):
    return str(
        job.apply_url
        or job.posting_url
        or ""
    ).strip()


def application_host(job):
    target = application_target(job)

    return (
        urlsplit(target).hostname
        or ""
    ).lower()


def get_submission_executor(job):
    # Central execution routing for Auto Apply.
    # ATS hosts are migrated into the Chrome Agent
    # framework here as their adapters become ready.
    host = application_host(job)

    if host in CHROME_AGENT_HOSTS:
        return EXECUTOR_CHROME_AGENT

    return EXECUTOR_LEGACY


def uses_chrome_agent(job):
    return (
        get_submission_executor(job)
        == EXECUTOR_CHROME_AGENT
    )
