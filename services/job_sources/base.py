
from abc import ABC, abstractmethod


class BaseJobSource(ABC):
    source_name = "Unknown"
    source_type = "unknown"
    requires_company_config = True

    @abstractmethod
    def search(self, profile, source_config=None):
        raise NotImplementedError(
            "Job sources must implement search()."
        )
        
          