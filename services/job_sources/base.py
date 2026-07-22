
class BaseJobSource:
    source_name = "base"

    def search(self, profile):
        raise NotImplementedError(
            "Job sources must implement search()."
        )
        