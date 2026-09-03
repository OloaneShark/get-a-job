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
AGENT_PATH = EXTENSION_ROOT / "remote_first_jobs_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "remote_first_jobs_agent_edge_cases.mjs"
BACKGROUND_EDGE_CASE_PATH = (
    ROOT / "tests" / "js" / "job_board_resolver_background_edge_cases.mjs"
)


class RemoteFirstJobsAgentTests(unittest.TestCase):
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

    def test_backend_routes_remote_first_jobs_to_the_resolver(self):
        job = self.job(
            "https://remotefirstjobs.com/companies/example/jobs/security-engineer-123"
        )
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(chrome_agent_adapter(job), "remote_first_jobs_resolver")
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_manifest_registers_both_remote_first_jobs_hosts(self):
        expected_hosts = {
            "https://remotefirstjobs.com/*",
            "https://www.remotefirstjobs.com/*",
        }
        self.assertTrue(expected_hosts.issubset(self.manifest["host_permissions"]))
        self.assertTrue(any(
            expected_hosts.issubset(set(script.get("matches", [])))
            and "remote_first_jobs_agent.js" in script.get("js", [])
            for script in self.manifest["content_scripts"]
        ))

    def test_resolver_updates_the_job_and_chains_to_a_supported_ats(self):
        listing_url = (
            "https://remotefirstjobs.com/companies/example/jobs/security-engineer-123"
        )
        resolved_url = "https://jobs.ashbyhq.com/example/application"
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(status="Approved", discovered_job=job)
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
        self.assertEqual(result["resolved_adapter"], "ashby_hosted")
        discover.assert_called_once()
        self.assertEqual(
            discover.call_args.args[2]["discovery_method"],
            "remote_first_jobs_browser_resolver",
        )

    def test_resolver_rejects_a_same_site_destination(self):
        listing_url = (
            "https://remotefirstjobs.com/companies/example/jobs/security-engineer-123"
        )
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(status="Approved", discovered_job=job)
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
            with self.assertRaisesRegex(ValueError, "invalid external application target"):
                apply_chrome_agent_result(
                    candidate,
                    SimpleNamespace(),
                    {
                        "status": "resolved_application_target",
                        "resolved_url": "https://remotefirstjobs.com/a/security-engineer-123",
                    },
                )

    def test_shared_resolver_path_preserves_himalayas_chaining(self):
        listing_url = "https://himalayas.app/companies/example/jobs/security-engineer"
        resolved_url = "https://jobs.lever.co/example/security-engineer/apply"
        job = SimpleNamespace(
            apply_url=listing_url,
            posting_url=listing_url,
            company_name="Example",
        )
        candidate = SimpleNamespace(status="Approved", discovered_job=job)
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
                return_value=None,
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

        self.assertTrue(result["continue_in_chrome_agent"])
        self.assertEqual(result["resolved_adapter"], "lever_hosted")
        self.assertEqual(
            discover.call_args.args[2]["discovery_method"],
            "himalayas_browser_resolver",
        )

    def test_background_tracks_child_tabs_and_preserves_resolver_identity(self):
        self.assertIn('"jobfinitum-job-board-watch"', self.background)
        self.assertIn('"jobfinitum-job-board-resolved"', self.background)
        self.assertIn('"remote_first_jobs_browser_agent"', self.background)
        self.assertIn('"remotefirstjobs.com"', self.background)
        self.assertIn("saveChainedAgentLaunch", self.background)

    def test_settings_show_remote_first_jobs_as_a_resolver(self):
        self.assertRegex(
            self.settings,
            r"<span>Remote First Jobs</span>\s*<strong>Browser Agent resolver</strong>",
        )

    def test_queue_keeps_ashby_and_remote_first_jobs_in_the_managed_runner(self):
        self.assertEqual(self.queue.count('"jobs.ashbyhq.com/"'), 2)
        self.assertEqual(self.queue.count('"remotefirstjobs.com/"'), 2)

    def test_feed_refresh_recognizes_an_unresolved_remote_first_jobs_url(self):
        self.assertIn('or "remotefirstjobs.com/" in current_apply_url', self.scheduler)

    def test_agent_has_no_submission_logic_of_its_own(self):
        self.assertIn('const ADAPTER = "remote_first_jobs_resolver"', self.source)
        self.assertIn('"needs_manual_destination"', self.source)
        self.assertIn('"jobfinitum-job-board-resolved"', self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertNotIn('status: "submitted"', self.source)


class RemoteFirstJobsAgentScriptTests(unittest.TestCase):
    def test_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent syntax tests.")
        subprocess.run(
            [node, "--check", str(AGENT_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_javascript_edge_cases(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent edge-case tests.")
        subprocess.run(
            [node, str(EDGE_CASE_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_background_javascript_edge_cases(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent edge-case tests.")
        subprocess.run(
            [node, str(BACKGROUND_EDGE_CASE_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
