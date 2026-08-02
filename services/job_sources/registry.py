
from services.job_sources.greenhouse import GreenhouseJobSource
from services.job_sources.lever import LeverJobSource
from services.job_sources.ashby import AshbyJobSource
from services.job_sources.remote_ok import RemoteOKJobSource
from services.job_sources.we_work_remotely import WeWorkRemotelyJobSource
from services.job_sources.remotive import RemotiveJobSource
from services.job_sources.himalayas import HimalayasJobSource
from services.job_sources.jobicy import JobicyJobSource
from services.job_sources.arbeitnow import ArbeitnowJobSource


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
