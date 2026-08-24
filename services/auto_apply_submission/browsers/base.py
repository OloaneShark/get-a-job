class BrowserSession:
    engine_name = "base"

    @property
    def page(self):
        raise NotImplementedError

    @property
    def human_handoff_available(self):
        return False

    def __enter__(self):
        raise NotImplementedError

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ):
        raise NotImplementedError
