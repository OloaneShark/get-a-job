import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.auto_apply_submission import chrome_agent_service
from services.auto_apply_submission.chrome_agent_service import (
    apply_chrome_agent_result,
    chrome_agent_adapter,
    chrome_agent_supports_job,
    chrome_agent_target,
    unsupported_candidate_became_retryable,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    EXECUTOR_LEGACY,
    application_target,
    embedded_greenhouse_application_target,
    get_submission_executor,
)
from services.job_sources.source_utils import (
    extract_greenhouse_board_token,
)


ROOT = Path(__file__).resolve().parents[1]
GREENHOUSE_AGENT_PATH = (
    ROOT
    / "browser_extensions"
    / "jobfinitum_chrome_agent"
    / "greenhouse_agent.js"
)
APP_PATH = ROOT / "app.py"


def job(url, company_name):
    return SimpleNamespace(
        apply_url=url,
        posting_url=url,
        company_name=company_name,
    )


class EmbeddedGreenhouseUrlTests(unittest.TestCase):
    def test_nebius_branded_url_is_left_for_rendered_page_scan(self):
        branded_url = (
            "https://careers.nebius.com/?gh_jid=4918253101"
            "&utm_source=himalayas.app"
        )
        discovered_job = job(branded_url, "Nebius")
        self.assertIsNone(
            embedded_greenhouse_application_target(discovered_job)
        )
        self.assertEqual(application_target(discovered_job), branded_url)
        self.assertEqual(chrome_agent_target(discovered_job), branded_url)
        self.assertTrue(chrome_agent_supports_job(discovered_job))
        self.assertEqual(
            chrome_agent_adapter(discovered_job),
            "employer_site_resolver",
        )
        self.assertEqual(
            get_submission_executor(discovered_job),
            EXECUTOR_CHROME_AGENT,
        )

    def test_gh_jid_without_board_metadata_is_not_guessed(self):
        discovered_job = job(
            (
                "https://jobs.example.com/opening"
                "?gh_jid=1234567"
            ),
            "Example Technologies, Inc.",
        )

        self.assertIsNone(
            embedded_greenhouse_application_target(discovered_job)
        )

    def test_explicit_board_token_wins_over_company_name(self):
        discovered_job = job(
            (
                "https://careers.example.com/opening"
                "?gh_jid=1234567&for=actual-board"
            ),
            "Different Company Name",
        )

        self.assertEqual(
            embedded_greenhouse_application_target(discovered_job),
            (
                "https://job-boards.greenhouse.io/embed/job_app"
                "?for=actual-board&token=1234567"
            ),
        )

    def test_non_greenhouse_urls_are_not_rewritten(self):
        original = "https://careers.example.com/opening?id=123"
        discovered_job = job(original, "Example")

        self.assertIsNone(
            embedded_greenhouse_application_target(discovered_job)
        )
        self.assertEqual(application_target(discovered_job), original)

        malformed = job(
            "https://careers.example.com/?gh_jid=not-a-number",
            "Example",
        )
        self.assertIsNone(
            embedded_greenhouse_application_target(malformed)
        )

    def test_embed_url_exposes_the_real_board_token(self):
        self.assertEqual(
            extract_greenhouse_board_token(
                (
                    "https://job-boards.greenhouse.io/embed/job_app"
                    "?for=nebius&token=4918253101"
                )
            ),
            "nebius",
        )

    def test_only_stale_adapter_classifications_are_retryable(self):
        branded_job = job(
            "https://careers.nebius.com/?gh_jid=4918253101",
            "Nebius",
        )
        candidate = SimpleNamespace(
            status="Approved",
            execution_status="Unsupported",
            discovered_job=branded_job,
        )

        self.assertTrue(
            unsupported_candidate_became_retryable(
                candidate,
                SimpleNamespace(adapter_name="himalayas_resolver"),
            )
        )
        self.assertFalse(
            unsupported_candidate_became_retryable(
                candidate,
            SimpleNamespace(adapter_name="employer_site_resolver"),
            )
        )

        unsupported_job = job(
            "https://jobs.smartrecruiters.com/example/123",
            "Example",
        )
        candidate.discovered_job = unsupported_job
        self.assertFalse(
            unsupported_candidate_became_retryable(
                candidate,
                SimpleNamespace(adapter_name="unsupported"),
            )
        )
        self.assertFalse(chrome_agent_supports_job(unsupported_job))
        self.assertEqual(
            get_submission_executor(unsupported_job),
            EXECUTOR_LEGACY,
        )

        candidate.discovered_job = branded_job
        candidate.status = "Rejected"
        self.assertFalse(
            unsupported_candidate_became_retryable(
                candidate,
                SimpleNamespace(adapter_name="himalayas_resolver"),
            )
        )

    def test_hosted_greenhouse_closed_result_removes_posting(self):
        branded_url = (
            "https://careers.nebius.com/?gh_jid=4918253101"
        )
        discovered_job = job(branded_url, "Nebius")
        candidate = SimpleNamespace(
            status="Approved",
            discovered_job=discovered_job,
        )
        prepared = {
            "ok": True,
            "application": SimpleNamespace(),
            "package": SimpleNamespace(),
            "identity": SimpleNamespace(),
        }

        with (
            patch.object(
                chrome_agent_service,
                "prepare_chrome_agent_candidate",
                return_value=prepared,
            ),
            patch.object(
                chrome_agent_service,
                "record_job_health_result",
                return_value={"removed": 1},
            ) as record_health,
            patch.object(
                chrome_agent_service.db.session,
                "flush",
            ),
        ):
            result = apply_chrome_agent_result(
                candidate,
                SimpleNamespace(),
                {
                    "status": "posting_closed",
                    "final_url": (
                        "https://job-boards.greenhouse.io/"
                        "embed/job_board?for=nebius&error=true"
                    ),
                },
            )

        self.assertEqual(result["status"], "Closed")
        self.assertTrue(result["posting_removed"])
        self.assertEqual(
            record_health.call_args.args[0]["posting_url"],
            branded_url,
        )
        self.assertEqual(
            record_health.call_args.args[0]["status"],
            "Closed",
        )


class EmbeddedGreenhouseSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.greenhouse_source = GREENHOUSE_AGENT_PATH.read_text(
            encoding="utf-8"
        )
        cls.app_source = APP_PATH.read_text(encoding="utf-8")

    def test_greenhouse_agent_supports_embed_and_closed_routes(self):
        self.assertIn(
            'parts[0] === "embed"',
            self.greenhouse_source,
        )
        self.assertIn(
            'params.get("for")',
            self.greenhouse_source,
        )
        self.assertIn(
            'params.get("token")',
            self.greenhouse_source,
        )
        self.assertIn(
            "function greenhousePostingClosed()",
            self.greenhouse_source,
        )
        self.assertIn(
            'status: "posting_closed"',
            self.greenhouse_source,
        )

    def test_queue_and_batch_recover_newly_supported_records(self):
        self.assertIn(
            "def _recover_newly_supported_manual_candidates(user_id):",
            self.app_source,
        )
        self.assertEqual(
            self.app_source.count(
                "_recover_newly_supported_manual_candidates(\n"
                "        current_user.id\n"
                "    )"
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
