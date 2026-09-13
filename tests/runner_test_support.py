from unittest.mock import patch

from services.auto_apply_submission import chrome_agent_service


class ResolverTransitionTestMixin:
    def setUp(self):
        # Resolver unit tests isolate routing; storage is covered with SQLite separately.
        self.enterContext(patch.object(
            chrome_agent_service, "_record_runner_transition",
            side_effect=lambda candidate, user, application, package, result, detail, adapter: result,
        ))
        self.enterContext(patch.object(chrome_agent_service.db.session, "flush"))

