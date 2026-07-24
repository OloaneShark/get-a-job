
from services.job_sources.greenhouse import GreenhouseJobSource
from services.job_sources.lever import LeverJobSource

SOURCE_REGISTRY = {
    "greenhouse": GreenhouseJobSource,
    "lever": LeverJobSource,
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
