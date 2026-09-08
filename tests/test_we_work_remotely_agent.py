import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.auto_apply_submission import chrome_agent_service
from services.auto_apply_submission.chrome_agent_service import (
    apply_chrome_agent_result,
    chrome_agent_adapter,
    chrome_agent_supports_job,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    get_submission_executor,
)


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "browser_extensions" / "jobfinitum_chrome_agent"
AGENT_PATH = EXTENSION_ROOT / "we_work_remotely_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "we_work_remotely_agent_edge_cases.mjs"
BACKGROUND_EDGE_CASE_PATH = (
    ROOT / "tests" / "js" / "job_board_resolver_background_edge_cases.mjs"
)


class WeWorkRemotelyAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.background = BACKGROUND_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.settings = SETTINGS_PATH.read_text(encoding="utf-8")
        cls.queue = QUEUE_PATH.read_text(encoding="utf-8")
        cls.scheduler = SCHEDULER_PATH.read_text(encoding="utf-8")

    @staticmethod
    def job(url):
        return SimpleNamespace(apply_url=url, posting_url=url)

    def test_backend_routes_we_work_remotely_to_the_resolver(self):
        job = self.job(
            "https://weworkremotely.com/remote-jobs/example-role"
        )
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(
            chrome_agent_adapter(job),
            "we_work_remotely_resolver",
        )
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_manifest_and_ui_register_we_work_remotely(self):
        expected_hosts = {
            "https://weworkremotely.com/*",
            "https://www.weworkremotely.com/*",
        }
        self.assertEqual(self.manifest["version"], "0.6.4")
        self.assertTrue(expected_hosts.issubset(
            self.manifest["host_permissions"]
        ))
        self.assertTrue(any(
            expected_hosts.issubset(set(script.get("matches", [])))
            and "we_work_remotely_agent.js" in script.get("js", [])
            for script in self.manifest["content_scripts"]
        ))
        self.assertRegex(
            self.settings,
            (
                r"<span>We Work Remotely</span>\s*"
                r"<strong>Browser Agent resolver</strong>"
            ),
        )
        self.assertEqual(self.queue.count('"weworkremotely.com/"'), 2)
        self.assertIn(
            'or "weworkremotely.com/" in current_apply_url',
            self.scheduler,
        )

    def test_resolver_updates_the_job_and_chains_to_greenhouse(self):
        listing_url = (
            "https://weworkremotely.com/remote-jobs/example-role"
        )
        resolved_url = (
            "https://job-boards.greenhouse.io/example/jobs/123"
        )
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(
            status="Approved",
            discovered_job=job,
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
                "_discover_resolver_source",
                return_value={"status": "created"},
            ) as discover,
            patch.object(chrome_agent_service.db.session, "flush"),
        ):
            result = apply_chrome_agent_result(
                candidate,
                SimpleNamespace(),
                {
                    "status": "resolved_application_target",
                    "resolved_url": resolved_url,
                },
            )

        self.assertEqual(job.apply_url, resolved_url)
        self.assertTrue(result["continue_in_chrome_agent"])
        self.assertEqual(result["resolved_adapter"], "greenhouse_hosted")
        self.assertEqual(
            discover.call_args.args[2]["discovery_method"],
            "we_work_remotely_browser_resolver",
        )

    def test_resolver_rejects_a_same_site_destination(self):
        listing_url = (
            "https://weworkremotely.com/remote-jobs/example-role"
        )
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(
            status="Approved",
            discovered_job=job,
        )
        prepared = {
            "ok": True,
            "application": SimpleNamespace(),
            "package": SimpleNamespace(),
            "identity": SimpleNamespace(),
        }

        with patch.object(
            chrome_agent_service,
            "prepare_chrome_agent_candidate",
            return_value=prepared,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "invalid external application target",
            ):
                apply_chrome_agent_result(
                    candidate,
                    SimpleNamespace(),
                    {
                        "status": "resolved_application_target",
                        "resolved_url": (
                            "https://weworkremotely.com/"
                            "remote-jobs/example-role/apply"
                        ),
                    },
                )

    def test_unsupported_employer_destination_falls_back_to_manual_apply(self):
        listing_url = (
            "https://weworkremotely.com/remote-jobs/example-role"
        )
        resolved_url = "https://apply.workable.com/example/j/123/apply/"
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(
            status="Approved",
            discovered_job=job,
        )
        prepared = {
            "ok": True,
            "application": SimpleNamespace(),
            "package": SimpleNamespace(),
            "identity": SimpleNamespace(),
        }
        manual_result = {
            "status": "Unsupported",
            "continue_in_chrome_agent": False,
            "manual_application": True,
        }
        with (
            patch.object(
                chrome_agent_service,
                "prepare_chrome_agent_candidate",
                return_value=prepared,
            ),
            patch.object(
                chrome_agent_service,
                "_discover_resolver_source",
                return_value=None,
            ),
            patch.object(chrome_agent_service.db.session, "flush"),
            patch.object(
                chrome_agent_service,
                "_record_resolver_manual_handoff",
                return_value=manual_result,
            ) as manual_handoff,
        ):
            result = apply_chrome_agent_result(
                candidate,
                SimpleNamespace(),
                {
                    "status": "resolved_application_target",
                    "resolved_url": resolved_url,
                },
            )

        self.assertEqual(result, manual_result)
        self.assertEqual(job.apply_url, resolved_url)
        self.assertIn(
            "apply.workable.com",
            manual_handoff.call_args.kwargs["message"],
        )

    def test_account_gate_is_saved_as_waiting_for_sign_in(self):
        listing_url = (
            "https://weworkremotely.com/remote-jobs/example-role"
        )
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(
            id=22,
            status="Approved",
            discovered_job=job,
            execution_status="Running",
            last_submission_attempt_at=None,
        )
        application = SimpleNamespace(id=33, status="Pending")
        package = SimpleNamespace(
            id=44,
            status="Prepared",
            failure_reason=None,
        )
        prepared = {
            "ok": True,
            "application": application,
            "package": package,
            "identity": SimpleNamespace(),
        }
        attempts = []

        with (
            patch.object(
                chrome_agent_service,
                "prepare_chrome_agent_candidate",
                return_value=prepared,
            ),
            patch.object(
                chrome_agent_service,
                "ApplicationSubmissionAttempt",
                side_effect=lambda **values: SimpleNamespace(**values),
            ),
            patch.object(
                chrome_agent_service.db.session,
                "add",
                side_effect=attempts.append,
            ),
        ):
            result = apply_chrome_agent_result(
                candidate,
                SimpleNamespace(id=11),
                {
                    "status": "waiting_sign_in",
                    "message": "Sign into We Work Remotely, then resume.",
                    "detail": {
                        "sign_in_url": (
                            "https://weworkremotely.com/"
                            "job-seekers/account/register"
                        ),
                    },
                },
            )

        self.assertEqual(result["status"], "Waiting for Sign-In")
        self.assertTrue(result["sign_in_required"])
        self.assertEqual(candidate.execution_status, "Waiting for Sign-In")
        self.assertEqual(
            application.status,
            "Auto Apply - Waiting for Sign-In",
        )
        self.assertEqual(package.status, "Waiting for Sign-In")
        self.assertEqual(attempts[0].status, "Waiting for Sign-In")
        detail = json.loads(attempts[0].detail_json)
        self.assertTrue(detail["sign_in_required"])
        self.assertEqual(
            detail["resolver"],
            "we_work_remotely_browser_agent",
        )

    def test_resolver_has_no_submission_logic_of_its_own(self):
        self.assertIn(
            'const ADAPTER = "we_work_remotely_resolver"',
            self.source,
        )
        self.assertIn('"waiting_sign_in"', self.source)
        self.assertIn('"needs_manual_destination"', self.source)
        self.assertIn('"jobfinitum-job-board-resolved"', self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertNotIn('status: "submitted"', self.source)
        self.assertIn(
            '"we_work_remotely_browser_agent"',
            self.background,
        )


class WeWorkRemotelyAgentScriptTests(unittest.TestCase):
    def test_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent syntax tests."
            )
        subprocess.run(
            [node, "--check", str(AGENT_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_javascript_edge_cases(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent edge-case tests."
            )
        subprocess.run(
            [node, str(EDGE_CASE_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_background_javascript_edge_cases(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent edge-case tests."
            )
        subprocess.run(
            [node, str(BACKGROUND_EDGE_CASE_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
