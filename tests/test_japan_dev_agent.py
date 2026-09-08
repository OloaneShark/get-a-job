import json
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup

from services.auto_apply_submission import chrome_agent_service
from services.auto_apply_submission.application_answer_service import (
    get_application_answer,
)
from services.auto_apply_submission.chrome_agent_service import (
    apply_chrome_agent_result,
    chrome_agent_adapter,
    chrome_agent_supports_job,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    get_submission_executor,
)
from services.job_sources.japan_dev import JapanDevJobSource


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "browser_extensions" / "jobfinitum_chrome_agent"
AGENT_PATH = EXTENSION_ROOT / "japan_dev_agent.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
SCHEDULER_PATH = ROOT / "services" / "scheduler_service.py"
DOCKERFILE_PATH = ROOT / "Dockerfile"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "japan_dev_agent_edge_cases.mjs"


class JapanDevSourceTests(unittest.TestCase):
    @staticmethod
    def soup(payload):
        return BeautifulSoup(
            '<script id="__NUXT_DATA__" type="application/json">'
            + json.dumps(payload)
            + "</script>",
            "html.parser",
        )

    def test_embedded_application_url_uses_the_current_job_record(self):
        employer_url = "https://jobs.lever.co/example/current/apply"
        payload = [
            None,
            {"slug": 2, "application_url": 3},
            "current-job",
            employer_url,
            {"slug": 5, "application_url": 6},
            "related-job",
            "https://jobs.ashbyhq.com/example/related",
        ]
        result = JapanDevJobSource.extract_embedded_application_url(
            self.soup(payload),
            "https://japan-dev.com/jobs/example/current-job",
        )
        self.assertEqual(result, employer_url)

    def test_embedded_application_url_rejects_same_site_and_malformed_data(self):
        same_site = [None, {"slug": 2, "application_url": 3}, "current-job",
                     "https://japan-dev.com/jobs/example/current-job"]
        self.assertIsNone(JapanDevJobSource.extract_embedded_application_url(
            self.soup(same_site),
            "https://japan-dev.com/jobs/example/current-job",
        ))
        malformed = BeautifulSoup(
            '<script id="__NUXT_DATA__">{broken</script>',
            "html.parser",
        )
        self.assertIsNone(JapanDevJobSource.extract_embedded_application_url(
            malformed,
            "https://japan-dev.com/jobs/example/current-job",
        ))

    def test_find_apply_url_prefers_embedded_data_over_related_links(self):
        employer_url = "https://apply.workable.com/example/j/123/apply/"
        soup = self.soup([
            None,
            {"slug": 2, "application_url": 3},
            "current-job",
            employer_url,
        ])
        related = soup.new_tag("a", href="https://jobs.lever.co/other/apply")
        related.string = "Apply"
        soup.append(related)
        self.assertEqual(
            JapanDevJobSource.find_apply_url(
                soup,
                "https://japan-dev.com/jobs/example/current-job",
            ),
            employer_url,
        )

    def test_language_and_overseas_conditions_are_extracted(self):
        lines = [
            "Apply from Anywhere",
            "Japanese: Conversational",
            "English: Business Level",
        ]
        page_text = " ".join(lines)
        self.assertEqual(
            JapanDevJobSource.detect_candidate_location(lines, page_text),
            "anywhere",
        )
        self.assertEqual(
            JapanDevJobSource.detect_overseas_status(lines, page_text),
            "Yes",
        )
        self.assertEqual(
            JapanDevJobSource.extract_language_level(lines, "Japanese"),
            "Conversational",
        )
        self.assertEqual(
            JapanDevJobSource.extract_language_level(lines, "English"),
            "Business Level",
        )


class JapanDevAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.settings = SETTINGS_PATH.read_text(encoding="utf-8")
        cls.queue = QUEUE_PATH.read_text(encoding="utf-8")
        cls.scheduler = SCHEDULER_PATH.read_text(encoding="utf-8")
        cls.dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    @staticmethod
    def job(url):
        return SimpleNamespace(apply_url=url, posting_url=url)

    def test_backend_routes_japan_dev_to_the_resolver(self):
        job = self.job("https://japan-dev.com/jobs/example/current-job")
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(chrome_agent_adapter(job), "japan_dev_resolver")
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_greenhouse_short_links_continue_to_the_greenhouse_agent(self):
        job = self.job("https://grnh.se/22b05aa38us")
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(chrome_agent_adapter(job), "greenhouse_hosted")
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_manifest_and_ui_register_japan_dev(self):
        expected_hosts = {
            "https://japan-dev.com/*",
            "https://www.japan-dev.com/*",
        }
        self.assertTrue(expected_hosts.issubset(self.manifest["host_permissions"]))
        self.assertTrue(any(
            expected_hosts.issubset(set(script.get("matches", [])))
            and "japan_dev_agent.js" in script.get("js", [])
            for script in self.manifest["content_scripts"]
        ))
        self.assertIn("<span>Japan Dev</span>", self.settings)
        self.assertEqual(self.queue.count('"japan-dev.com/"'), 2)
        self.assertIn('or "japan-dev.com/" in current_apply_url', self.scheduler)
        self.assertIn(
            "python migrate_application_answer_profile.py",
            self.dockerfile,
        )

    def test_resolver_chains_to_a_supported_ats(self):
        listing_url = "https://japan-dev.com/jobs/example/current-job"
        resolved_url = "https://jobs.lever.co/example/current-job/apply"
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

        self.assertEqual(job.apply_url, resolved_url)
        self.assertTrue(result["continue_in_chrome_agent"])
        self.assertEqual(result["resolved_adapter"], "lever_hosted")
        self.assertEqual(
            discover.call_args.args[2]["discovery_method"],
            "japan_dev_browser_resolver",
        )

    def test_resolver_sends_an_unsupported_employer_board_to_manual_apply(self):
        listing_url = "https://japan-dev.com/jobs/example/current-job"
        resolved_url = "https://apply.workable.com/example/j/123/apply/"
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

    def test_reusable_language_and_residency_answers_do_not_guess(self):
        identity = SimpleNamespace(
            japanese_proficiency="Conversational",
            english_proficiency="Fluent",
            currently_residing_in_japan="No",
        )
        self.assertEqual(
            get_application_answer(
                identity,
                "Are you fluent in Japanese?",
            )["value"],
            "Conversational",
        )
        self.assertEqual(
            get_application_answer(
                identity,
                "Do you currently reside in Japan?",
            )["value"],
            "No",
        )
        identity.japanese_proficiency = "Unknown"
        self.assertIsNone(get_application_answer(
            identity,
            "What is your Japanese proficiency?",
        ))

    def test_resolver_has_no_submission_logic(self):
        self.assertIn('const ADAPTER = "japan_dev_resolver"', self.source)
        self.assertIn('"needs_manual_destination"', self.source)
        self.assertIn('"jobfinitum-job-board-resolved"', self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertNotIn('status: "submitted"', self.source)


class JapanDevAgentScriptTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
