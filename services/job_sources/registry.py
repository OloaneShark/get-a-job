
from services.job_sources.greenhouse import GreenhouseJobSource
from services.job_sources.lever import LeverJobSource
from services.job_sources.ashby import AshbyJobSource
from services.job_sources.remote_ok import RemoteOKJobSource
from services.job_sources.we_work_remotely import WeWorkRemotelyJobSource
from services.job_sources.remotive import RemotiveJobSource
from services.job_sources.himalayas import HimalayasJobSource
from services.job_sources.jobicy import JobicyJobSource
from services.job_sources.arbeitnow import ArbeitnowJobSource
from services.job_sources.japan_dev import JapanDevJobSource
from services.job_sources.tokyo_dev import TokyoDevJobSource
from services.job_sources.workday import WorkdayJobSource
from services.job_sources.recruitee import RecruiteeJobSource
from services.job_sources.adzuna import AdzunaJobSource
from services.job_sources.jooble import JoobleJobSource
from services.job_sources.usajobs import USAJobsJobSource
from services.job_sources.the_muse import TheMuseJobSource
from services.job_sources.python_org import PythonOrgJobSource
from services.job_sources.hacker_news_jobs import HackerNewsJobsSource
from services.job_sources.cncf_gitjobs import CNCFGitJobsSource
from services.job_sources.remote_first_jobs import RemoteFirstJobsSource
from services.job_sources.y_combinator import YCombinatorJobSource
from services.job_sources.ai_dev_jobs import AIDevJobsSource
from services.job_sources.green_japan import GreenJapanJobSource
from services.job_sources.bamboohr import BambooHRJobSource
from services.job_sources.workable import WorkableJobSource
from services.job_sources.amazon_jobs import AmazonJobsSource
from services.job_sources.apple_jobs import AppleJobsSource


SOURCE_REGISTRY = {
    "greenhouse": GreenhouseJobSource,
    "lever": LeverJobSource,
    "ashby": AshbyJobSource,
    "remote_ok": RemoteOKJobSource,
    "we_work_remotely": WeWorkRemotelyJobSource,
    "remotive": RemotiveJobSource,
    "himalayas": HimalayasJobSource,
    "jobicy": JobicyJobSource,
    "arbeitnow": ArbeitnowJobSource,
    "japan_dev": JapanDevJobSource,
    "tokyo_dev": TokyoDevJobSource,
    "workday": WorkdayJobSource,
    "recruitee": RecruiteeJobSource,
    "adzuna": AdzunaJobSource,
    "jooble": JoobleJobSource,
    "usajobs": USAJobsJobSource,
    "the_muse": TheMuseJobSource,
    "python_org": PythonOrgJobSource,
    "hacker_news_jobs": HackerNewsJobsSource,
    "cncf_gitjobs": CNCFGitJobsSource,
    "remote_first_jobs": RemoteFirstJobsSource,
    "y_combinator": YCombinatorJobSource,
    "ai_dev_jobs": AIDevJobsSource,
    "green_japan": GreenJapanJobSource,
    "bamboohr": BambooHRJobSource,
    "workable": WorkableJobSource,
    "amazon_jobs": AmazonJobsSource,
    "apple_jobs": AppleJobsSource,
}


def get_source_class(source_type):
    if not source_type:
        return None

    return SOURCE_REGISTRY.get(
        source_type.strip().lower()
    )


def create_source(source_type):
    source_class = get_source_class(source_type)

    if source_class is None:
        raise ValueError(
            f"Unsupported job source type: {source_type}"
        )

    return source_class()
