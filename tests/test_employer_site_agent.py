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
    unsupported_candidate_became_retryable,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    EXECUTOR_LEGACY,
    get_submission_executor,
)


ROOT = Path(__file__).resolve().parents[1]
EXTENSION_ROOT = ROOT / "browser_extensions" / "jobfinitum_chrome_agent"
AGENT_PATH = EXTENSION_ROOT / "employer_site_agent.js"
BACKGROUND_PATH = EXTENSION_ROOT / "background.js"
MANIFEST_PATH = EXTENSION_ROOT / "manifest.json"
QUEUE_PATH = ROOT / "templates" / "auto_apply_queue.html"
EDGE_CASE_PATH = ROOT / "tests" / "js" / "employer_site_agent_edge_cases.mjs"


from tests.runner_test_support import ResolverTransitionTestMixin


class EmployerSiteAgentTests(ResolverTransitionTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.background = BACKGROUND_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(
            MANIFEST_PATH.read_text(encoding="utf-8")
        )
        cls.queue = QUEUE_PATH.read_text(encoding="utf-8")

    @staticmethod
    def job(url, *, posting_url=None):
        return SimpleNamespace(
            apply_url=url,
            posting_url=posting_url or url,
            company_name="Example",
        )

    @staticmethod
    def candidate_for(url):
        job = EmployerSiteAgentTests.job(url)
        return job, SimpleNamespace(
            status="Approved",
            execution_status="Unsupported",
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

    def test_arbitrary_https_pages_do_not_use_wrapper_resolver(self):
        job = self.job(
            "https://careers.example.com/jobs/platform-engineer"
        )

        self.assertFalse(chrome_agent_supports_job(job))
        self.assertEqual(
            get_submission_executor(job),
            EXECUTOR_LEGACY,
        )

    def test_middleman_destination_uses_wrapper_resolver(self):
        job = self.job(
            "https://careers.example.com/jobs/platform-engineer",
            posting_url=(
                "https://himalayas.app/companies/example/"
                "jobs/platform-engineer"
            ),
        )

        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(
            chrome_agent_adapter(job),
            "employer_site_resolver",
        )
        self.assertEqual(
            get_submission_executor(job),
            EXECUTOR_CHROME_AGENT,
        )

    def test_known_unsupported_ats_skips_wrapper_scan(self):
        for url in (
            (
                "https://nvidia.wd5.myworkdayjobs.com/en-US/"
                "NVIDIAExternalCareerSite/job/example"
            ),
            (
                "https://workforcenow.adp.com/mascsr/default/"
                "mdf/recruitment/recruitment.html"
            ),
            "https://jobs.smartrecruiters.com/example/123",
            "https://example.avature.net/careers/JobDetail/123",
            "https://konnecthub.zohorecruit.com.au/jobs/role",
        ):
            with self.subTest(url=url):
                job = self.job(
                    url,
                    posting_url=(
                        "https://himalayas.app/companies/example/jobs/role"
                    ),
                )
                self.assertFalse(chrome_agent_supports_job(job))
                self.assertEqual(
                    get_submission_executor(job),
                    EXECUTOR_LEGACY,
                )

    def test_local_and_non_https_pages_do_not_use_wrapper_resolver(self):
        for url in (
            "http://127.0.0.1:5000/jobs/example",
            "http://careers.example.com/jobs/example",
            "not-a-url",
        ):
            with self.subTest(url=url):
                job = self.job(url)
                self.assertFalse(chrome_agent_supports_job(job))
                self.assertEqual(
                    get_submission_executor(job),
                    EXECUTOR_LEGACY,
                )

    def test_known_hosted_adapter_keeps_priority(self):
        job = self.job(
            "https://jobs.ashbyhq.com/example/role/application"
        )

        self.assertEqual(
            chrome_agent_adapter(job),
            "ashby_hosted",
        )

    def test_wrapper_result_chains_to_every_supported_destination_type(self):
        destinations = {
            (
                "https://job-boards.greenhouse.io/acme/jobs/123"
            ): "greenhouse_hosted",
            "https://jobs.lever.co/acme/role/apply": "lever_hosted",
            (
                "https://jobs.ashbyhq.com/acme/role/application"
            ): "ashby_hosted",
            (
                "https://www.themuse.com/jobs/acme/platform-engineer"
            ): "the_muse_resolver",
        }

        for resolved_url, expected_adapter in destinations.items():
            with self.subTest(resolved_url=resolved_url):
                job, candidate = self.candidate_for(
                    (
                        "https://careers.acme.example/platform-engineer"
                        "?gh_jid=123456"
                    )
                )

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
                    ),
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

    def test_unknown_destination_is_not_chained_back_into_wrapper_resolver(self):
        job, candidate = self.candidate_for(
            (
                "https://careers.acme.example/platform-engineer"
                "?gh_jid=123456"
            )
        )
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
                chrome_agent_service,
                "remember_host_classification",
            ) as remember,
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
                    "resolved_url": (
                        "https://apply.unknown.example/application/123"
                    ),
                },
            )

        self.assertEqual(result, manual_result)
        self.assertIn(
            "apply.unknown.example",
            manual_handoff.call_args.kwargs["message"],
        )
        self.assertEqual(
            remember.call_args.args[1],
            "unsupported_destination",
        )

    def test_prior_manual_records_get_one_wrapper_rescan(self):
        _, candidate = self.candidate_for(
            (
                "https://careers.acme.example/platform-engineer"
                "?gh_jid=123456"
            )
        )

        self.assertTrue(
            unsupported_candidate_became_retryable(
                candidate,
                SimpleNamespace(adapter_name="unsupported"),
            )
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

    def test_manifest_registers_the_limited_all_site_scanner(self):
        self.assertEqual(self.manifest["version"], "0.6.17")
        self.assertIn(
            "https://*/*",
            self.manifest["host_permissions"],
        )
        matching_scripts = [
            script
            for script in self.manifest["content_scripts"]
            if script.get("matches") == ["https://*/*"]
            and "employer_site_agent.js" in script.get("js", [])
        ]
        self.assertEqual(len(matching_scripts), 1)
        self.assertEqual(
            matching_scripts[0].get("run_at"),
            "document_start",
        )
        self.assertIn(
            'const ADAPTER = "employer_site_resolver"',
            self.source,
        )
        self.assertNotIn('status: "submitted"', self.source)
        self.assertNotIn("Submit Application", self.source)
        self.assertIn(
            'return "employer_site_browser_agent";',
            self.background,
        )
        self.assertNotIn(
            '.startswith("https://")',
            self.queue,
        )
        self.assertIn(
            "candidate.id in chrome_agent_candidate_ids",
            self.queue,
        )
        self.assertNotIn("answer_uses_chrome_agent", self.queue)
        self.assertNotIn('"gh_jid=" in', self.queue)

    def test_resolved_hosted_ats_is_remembered_as_positive_evidence(self):
        original_url = (
            "https://careers.acme.example/platform-engineer"
            "?gh_jid=123456"
        )
        _, candidate = self.candidate_for(original_url)

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
                chrome_agent_service,
                "remember_host_classification",
            ) as remember,
            patch.object(
                chrome_agent_service.db.session,
                "flush",
            ),
        ):
            apply_chrome_agent_result(
                candidate,
                SimpleNamespace(),
                {
                    "status": "resolved_application_target",
                    "resolved_url": (
                        "https://jobs.lever.co/acme/role/apply"
                    ),
                },
            )

        self.assertEqual(remember.call_args.args[0], original_url)
        self.assertEqual(
            remember.call_args.args[1],
            "supported_wrapper",
        )
        self.assertEqual(
            remember.call_args.kwargs["adapter_name"],
            "lever_hosted",
        )

    def test_no_target_is_cached_but_transient_resolver_error_is_not(self):
        target = "https://careers.acme.example/platform-engineer"
        job = self.job(
            target,
            posting_url=(
                "https://himalayas.app/companies/acme/"
                "jobs/platform-engineer"
            ),
        )
        candidate = SimpleNamespace(
            status="Approved",
            execution_status="Unsupported",
            discovered_job=job,
        )
        manual_result = {
            "status": "Unsupported",
            "manual_application": True,
        }

        for detail, expected_calls in (({}, 1), ({"error": "timeout"}, 0)):
            with self.subTest(detail=detail):
                with (
                    patch.object(
                        chrome_agent_service,
                        "prepare_chrome_agent_candidate",
                        return_value=self.prepared(),
                    ),
                    patch.object(
                        chrome_agent_service,
                        "remember_host_classification",
                    ) as remember,
                    patch.object(
                        chrome_agent_service,
                        "_record_resolver_manual_handoff",
                        return_value=manual_result,
                    ),
                ):
                    apply_chrome_agent_result(
                        candidate,
                        SimpleNamespace(),
                        {
                            "status": "needs_manual_destination",
                            "detail": detail,
                        },
                    )

                self.assertEqual(remember.call_count, expected_calls)


class EmployerSiteAgentScriptTests(unittest.TestCase):
    def test_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent syntax tests."
            )
        subprocess.run(
            [node, "--check", str(AGENT_PATH)],
            check=True,
        )

    def test_edge_case_harness(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent edge-case tests."
            )
        completed = subprocess.run(
            [node, str(EDGE_CASE_PATH)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=completed.stdout + completed.stderr,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["failed"], 0)


if __name__ == "__main__":
    unittest.main()
