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
AGENT_PATH = EXTENSION_ROOT / "remote_ok_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
README_PATH = EXTENSION_ROOT / "README.md"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "remote_ok_agent_edge_cases.mjs"
BACKGROUND_EDGE_CASE_PATH = (
    ROOT / "tests" / "js" / "job_board_resolver_background_edge_cases.mjs"
)


class RemoteOKAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.background = BACKGROUND_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.settings = SETTINGS_PATH.read_text(encoding="utf-8")
        cls.queue = QUEUE_PATH.read_text(encoding="utf-8")
        cls.scheduler = SCHEDULER_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    @staticmethod
    def job(url):
        return SimpleNamespace(apply_url=url, posting_url=url)

    @staticmethod
    def candidate_for(url):
        job = SimpleNamespace(
            apply_url=url,
            posting_url=url,
            company_name="Example",
        )
        return job, SimpleNamespace(
            status="Approved",
            discovered_job=job,
        )

    @staticmethod
    def prepared():
        return {
            "ok": True,
            "application": SimpleNamespace(),
            "package": SimpleNamespace(),
            "identity": SimpleNamespace(),
        }

    def test_backend_routes_remote_ok_to_the_resolver(self):
        job = self.job("https://remoteok.com/remote-jobs/example-role-123")
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(chrome_agent_adapter(job), "remote_ok_resolver")
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_manifest_and_ui_register_remote_ok(self):
        expected_hosts = {
            "https://remoteok.com/*",
            "https://www.remoteok.com/*",
        }
        self.assertEqual(self.manifest["version"], "0.6.12")
        self.assertTrue(expected_hosts.issubset(
            self.manifest["host_permissions"]
        ))
        matching_scripts = [
            script
            for script in self.manifest["content_scripts"]
            if expected_hosts.issubset(set(script.get("matches", [])))
            and "remote_ok_agent.js" in script.get("js", [])
        ]
        self.assertEqual(len(matching_scripts), 1)
        self.assertEqual(matching_scripts[0].get("run_at"), "document_start")
        self.assertIn("webNavigation", self.manifest["permissions"])
        self.assertRegex(
            self.settings,
            r"<span>Remote OK</span>\s*<strong>Browser Agent resolver</strong>",
        )
        self.assertEqual(self.queue.count('"remoteok.com/"'), 2)
        self.assertIn('or "remoteok.com/" in current_apply_url', self.scheduler)
        self.assertIn("Remote OK employer-site redirect resolver", self.readme)

    def test_resolver_updates_the_job_and_chains_to_greenhouse(self):
        listing_url = "https://remoteok.com/remote-jobs/example-role-123"
        resolved_url = "https://job-boards.greenhouse.io/example/jobs/123"
        job, candidate = self.candidate_for(listing_url)

        with (
            patch.object(
                chrome_agent_service,
                "prepare_chrome_agent_candidate",
                return_value=self.prepared(),
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
            "remote_ok_browser_resolver",
        )

    def test_resolver_rejects_a_same_site_destination(self):
        job, candidate = self.candidate_for("https://remoteok.com/remote-jobs/example-role-123")

        with patch.object(
            chrome_agent_service,
            "prepare_chrome_agent_candidate",
            return_value=self.prepared(),
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
                        "resolved_url": "https://www.remoteok.com/l/456",
                    },
                )

        self.assertEqual(job.apply_url, "https://remoteok.com/remote-jobs/example-role-123")

    def test_unsupported_destination_falls_back_to_manual_apply(self):
        resolved_url = "https://apply.workable.com/example/j/123/apply/"
        job, candidate = self.candidate_for("https://remoteok.com/remote-jobs/example-role-123")
        manual_result = {
            "status": "Unsupported",
            "continue_in_chrome_agent": False,
            "manual_application": True,
        }

        with (
            patch.object(
                chrome_agent_service,
                "prepare_chrome_agent_candidate",
                return_value=self.prepared(),
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

    def test_challenge_is_saved_as_waiting_for_verification(self):
        job = SimpleNamespace(
            apply_url="https://remoteok.com/remote-jobs/example-role-123",
            posting_url="https://remoteok.com/remote-jobs/example-role-123",
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
                    "status": "waiting_verification",
                    "message": "Complete the visible Remote OK challenge.",
                    "detail": {"url": "https://remoteok.com/remote-jobs/example-role-123"},
                },
            )

        self.assertEqual(result["status"], "Waiting for Verification")
        self.assertTrue(result["verification_required"])
        self.assertEqual(candidate.execution_status, "Waiting for Verification")
        self.assertEqual(
            application.status,
            "Auto Apply - Waiting for Verification",
        )
        self.assertEqual(package.status, "Waiting for Verification")
        self.assertEqual(attempts[0].status, "Waiting for Verification")
        detail = json.loads(attempts[0].detail_json)
        self.assertTrue(detail["verification_required"])
        self.assertEqual(detail["resolver"], "remote_ok_browser_agent")

    def test_resolver_has_no_submission_logic_of_its_own(self):
        self.assertIn('const ADAPTER = "remote_ok_resolver"', self.source)
        self.assertIn('"waiting_verification"', self.source)
        self.assertIn('"needs_manual_destination"', self.source)
        self.assertIn('"jobfinitum-job-board-watch"', self.source)
        self.assertIn('"jobfinitum-job-board-restore"', self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertNotIn('status: "submitted"', self.source)
        self.assertIn('"remote_ok_browser_agent"', self.background)
        self.assertIn("registerResolverLaunchFromUrl", self.background)


class RemoteOKAgentScriptTests(unittest.TestCase):
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
