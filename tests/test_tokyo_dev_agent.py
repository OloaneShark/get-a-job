import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

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
from services.job_sources.tokyo_dev import TokyoDevJobSource


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "browser_extensions" / "jobfinitum_chrome_agent"
AGENT_PATH = EXTENSION_ROOT / "tokyo_dev_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
README_PATH = EXTENSION_ROOT / "README.md"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "tokyo_dev_agent_edge_cases.mjs"
BACKGROUND_EDGE_CASE_PATH = (
    ROOT / "tests" / "js" / "job_board_resolver_background_edge_cases.mjs"
)


class TokyoDevAgentTests(unittest.TestCase):
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

    def test_source_keeps_the_real_tokyodev_application_route(self):
        posting_url = (
            "https://www.tokyodev.com/companies/acme/"
            "jobs/platform-engineer"
        )
        soup = BeautifulSoup(
            """
            <a href="/about">About</a>
            <a href="/c/acme/j/platform-engineer/applications/new">
                Continue applying
            </a>
            """,
            "html.parser",
        )

        self.assertEqual(
            TokyoDevJobSource.find_apply_url(soup, posting_url),
            (
                "https://www.tokyodev.com/c/acme/j/"
                "platform-engineer/applications/new"
            ),
        )

    def test_source_falls_back_to_the_listing_without_an_apply_route(self):
        posting_url = (
            "https://www.tokyodev.com/companies/acme/"
            "jobs/platform-engineer"
        )
        soup = BeautifulSoup("<a href='/about'>About</a>", "html.parser")
        self.assertEqual(
            TokyoDevJobSource.find_apply_url(soup, posting_url),
            posting_url,
        )

    def test_backend_routes_tokyodev_to_the_resolver(self):
        job = self.job(
            "https://www.tokyodev.com/c/acme/j/"
            "platform-engineer/applications/new"
        )
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(
            chrome_agent_adapter(job),
            "tokyo_dev_resolver",
        )
        self.assertEqual(
            get_submission_executor(job),
            EXECUTOR_CHROME_AGENT,
        )

    def test_manifest_and_ui_register_tokyodev(self):
        expected_hosts = {
            "https://tokyodev.com/*",
            "https://www.tokyodev.com/*",
        }
        self.assertEqual(self.manifest["version"], "0.6.7")
        self.assertTrue(
            expected_hosts.issubset(
                self.manifest["host_permissions"]
            )
        )
        matching_scripts = [
            script
            for script in self.manifest["content_scripts"]
            if expected_hosts.issubset(set(script.get("matches", [])))
            and "tokyo_dev_agent.js" in script.get("js", [])
        ]
        self.assertEqual(len(matching_scripts), 1)
        self.assertEqual(
            matching_scripts[0].get("run_at"),
            "document_start",
        )
        self.assertIn("webNavigation", self.manifest["permissions"])
        self.assertRegex(
            self.settings,
            (
                r"<span>TokyoDev</span>\s*"
                r"<strong>Browser Agent resolver</strong>"
            ),
        )
        self.assertEqual(self.queue.count('"tokyodev.com/"'), 2)
        self.assertIn(
            'or "tokyodev.com/" in current_apply_url',
            self.scheduler,
        )
        self.assertIn(
            "TokyoDev employer-application redirect resolver",
            self.readme,
        )

    def test_resolver_updates_the_job_and_chains_to_greenhouse(self):
        listing_url = (
            "https://www.tokyodev.com/c/acme/j/"
            "platform-engineer/applications/new"
        )
        resolved_url = (
            "https://job-boards.greenhouse.io/acme/jobs/123"
        )
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
        self.assertEqual(
            result["resolved_adapter"],
            "greenhouse_hosted",
        )
        self.assertEqual(
            discover.call_args.args[2]["discovery_method"],
            "tokyo_dev_browser_resolver",
        )

    def test_unsupported_destination_falls_back_to_manual_apply(self):
        listing_url = (
            "https://www.tokyodev.com/c/acme/j/"
            "platform-engineer/applications/new"
        )
        resolved_url = (
            "https://apply.workable.com/acme/j/ABC123/"
        )
        job, candidate = self.candidate_for(listing_url)
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

    def test_resolver_rejects_a_same_site_destination(self):
        listing_url = (
            "https://www.tokyodev.com/c/acme/j/"
            "platform-engineer/applications/new"
        )
        job, candidate = self.candidate_for(listing_url)

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
                        "resolved_url": (
                            "https://www.tokyodev.com/jobs"
                        ),
                    },
                )

        self.assertEqual(job.apply_url, listing_url)

    def test_resolver_only_affirms_explicit_japan_residency(self):
        self.assertIn(
            'currently_residing_in_japan',
            self.source,
        )
        self.assertIn(
            'answer !== "yes"',
            self.source,
        )
        self.assertIn(
            '"resident of japan"',
            self.source,
        )
        self.assertIn(
            '"needs_manual_destination"',
            self.source,
        )

    def test_resolver_has_no_application_submission_logic(self):
        self.assertIn(
            'const ADAPTER = "tokyo_dev_resolver"',
            self.source,
        )
        self.assertIn(
            '"waiting_verification"',
            self.source,
        )
        self.assertIn(
            '"jobfinitum-job-board-watch"',
            self.source,
        )
        self.assertIn(
            '"jobfinitum-job-board-restore"',
            self.source,
        )
        self.assertNotIn("window.open(", self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertNotIn('status: "submitted"', self.source)
        self.assertIn(
            '"tokyo_dev_browser_agent"',
            self.background,
        )
        self.assertIn(
            "registerResolverLaunchFromUrl",
            self.background,
        )


class TokyoDevAgentScriptTests(unittest.TestCase):
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
