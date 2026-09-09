import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services.auto_apply_submission import chrome_agent_service
from services.auto_apply_submission.chrome_agent_service import (
    THE_MUSE_HOSTS,
    apply_chrome_agent_result,
    chrome_agent_adapter,
    chrome_agent_supports_job,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    get_submission_executor,
)
from services.job_sources.the_muse import TheMuseJobSource


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "browser_extensions" / "jobfinitum_chrome_agent"
AGENT_PATH = EXTENSION_ROOT / "the_muse_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
README_PATH = EXTENSION_ROOT / "README.md"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "the_muse_agent_edge_cases.mjs"
BACKGROUND_EDGE_CASE_PATH = (
    ROOT / "tests" / "js" / "job_board_resolver_background_edge_cases.mjs"
)


class TheMuseAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.background = BACKGROUND_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.settings = SETTINGS_PATH.read_text(encoding="utf-8")
        cls.queue = QUEUE_PATH.read_text(encoding="utf-8")
        cls.scheduler = SCHEDULER_PATH.read_text(encoding="utf-8")
        cls.readme = README_PATH.read_text(encoding="utf-8")

    @staticmethod
    def job(url):
        return SimpleNamespace(
            apply_url=url,
            posting_url=url,
        )

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

    def test_source_preserves_the_muse_landing_page(self):
        listing_url = (
            "https://www.themuse.com/jobs/acme/"
            "platform-engineer"
        )
        job = TheMuseJobSource.normalize_job(
            {
                "id": 123,
                "name": "Platform Engineer",
                "company": {"name": "Acme"},
                "contents": "Build the platform.",
                "locations": [{"name": "Remote"}],
                "categories": [
                    {"name": "Software Engineering"},
                ],
                "levels": [{"name": "Mid Level"}],
                "refs": {"landing_page": listing_url},
            },
            {"scope_location": None},
        )

        self.assertEqual(job["posting_url"], listing_url)
        self.assertEqual(job["apply_url"], listing_url)

    def test_backend_routes_both_the_muse_hosts(self):
        self.assertEqual(
            THE_MUSE_HOSTS,
            {"themuse.com", "www.themuse.com"},
        )

        for host in THE_MUSE_HOSTS:
            with self.subTest(host=host):
                job = self.job(
                    f"https://{host}/jobs/acme/platform-engineer"
                )
                self.assertTrue(
                    chrome_agent_supports_job(job)
                )
                self.assertEqual(
                    chrome_agent_adapter(job),
                    "the_muse_resolver",
                )
                self.assertEqual(
                    get_submission_executor(job),
                    EXECUTOR_CHROME_AGENT,
                )

    def test_manifest_and_ui_register_the_muse(self):
        expected_patterns = {
            "https://themuse.com/*",
            "https://www.themuse.com/*",
        }
        self.assertEqual(
            self.manifest["version"],
            "0.6.9",
        )
        self.assertTrue(
            expected_patterns.issubset(
                self.manifest["host_permissions"]
            )
        )
        matching_scripts = [
            script
            for script in self.manifest["content_scripts"]
            if expected_patterns.issubset(
                set(script.get("matches", []))
            )
            and "the_muse_agent.js" in script.get("js", [])
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
                r"<span>The Muse</span>\s*"
                r"<strong>Browser Agent resolver</strong>"
            ),
        )
        for prefix in (
            "application_target",
            "answer_application_target",
        ):
            self.assertEqual(
                self.queue.count(
                    f'or "themuse.com/" in {prefix}'
                ),
                1,
            )
            self.assertEqual(
                self.queue.count(
                    f'or "www.themuse.com/" in {prefix}'
                ),
                1,
            )
        self.assertIn(
            'or "themuse.com/" in current_apply_url',
            self.scheduler,
        )
        self.assertIn(
            "The Muse employer-application data resolver",
            self.readme,
        )

    def test_resolver_updates_job_and_chains_to_supported_ats(self):
        listing_url = (
            "https://www.themuse.com/jobs/acme/"
            "platform-engineer"
        )
        destinations = {
            "https://jobs.lever.co/acme/role/apply": (
                "lever_hosted"
            ),
            (
                "https://job-boards.greenhouse.io/"
                "acme/jobs/123"
            ): "greenhouse_hosted",
        }

        for resolved_url, expected_adapter in destinations.items():
            with self.subTest(resolved_url=resolved_url):
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
                    patch.object(
                        chrome_agent_service.db.session,
                        "flush",
                    ),
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
                    expected_adapter,
                )
                self.assertEqual(
                    discover.call_args.args[2]["discovery_method"],
                    "the_muse_browser_resolver",
                )

    def test_unsupported_destination_falls_back_to_manual(self):
        listing_url = (
            "https://www.themuse.com/jobs/acme/"
            "platform-engineer"
        )
        resolved_url = (
            "https://acme.wd5.myworkdayjobs.com/"
            "careers/job/platform-engineer"
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
            patch.object(
                chrome_agent_service.db.session,
                "flush",
            ),
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
            "myworkdayjobs.com",
            manual_handoff.call_args.kwargs["message"],
        )

    def test_resolver_rejects_same_site_destination(self):
        listing_url = (
            "https://www.themuse.com/jobs/acme/"
            "platform-engineer"
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
                        "resolved_url": listing_url,
                    },
                )

        self.assertEqual(job.apply_url, listing_url)

    def test_resolver_has_no_submission_logic(self):
        self.assertIn(
            'const ADAPTER = "the_muse_resolver"',
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
            '"the_muse_browser_agent"',
            self.background,
        )
        self.assertIn(
            "registerResolverLaunchFromUrl",
            self.background,
        )


class TheMuseAgentScriptTests(unittest.TestCase):
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
