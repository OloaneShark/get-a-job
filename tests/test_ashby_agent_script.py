import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace

from services.auto_apply_submission.chrome_agent_service import (
    chrome_agent_adapter,
    chrome_agent_supports_job,
)
from services.auto_apply_submission.executor_router import (
    EXECUTOR_CHROME_AGENT,
    get_submission_executor,
)

ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "browser_extensions" / "jobfinitum_chrome_agent" / "ashby_agent.js"
MANIFEST_PATH = ROOT / "browser_extensions" / "jobfinitum_chrome_agent" / "manifest.json"
SITE_SCRIPT_PATH = ROOT / "static" / "js" / "chrome_agent_site.js"
SETTINGS_PATH = ROOT / "templates" / "browser_agent_settings.html"

class AshbyAgentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.site_source = SITE_SCRIPT_PATH.read_text(encoding="utf-8")
        cls.settings_source = SETTINGS_PATH.read_text(encoding="utf-8")

    def test_manifest_registers_ashby(self):
        self.assertEqual(self.manifest["version"], "0.5.1")
        self.assertIn("https://jobs.ashbyhq.com/*", self.manifest["host_permissions"])
        self.assertTrue(any(
            "https://jobs.ashbyhq.com/*" in script.get("matches", [])
            and "ashby_agent.js" in script.get("js", [])
            for script in self.manifest["content_scripts"]
        ))

    def test_every_site_handshake_requires_the_manifest_version(self):
        required_versions = re.findall(
            r"REQUIRED_AGENT_VERSION\s*=\s*\"([^\"]+)\"",
            self.site_source,
        )
        self.assertGreaterEqual(len(required_versions), 2)
        self.assertEqual(set(required_versions), {self.manifest["version"]})

    def test_backend_routes_ashby_to_the_chrome_agent(self):
        job = SimpleNamespace(
            apply_url="https://jobs.ashbyhq.com/example/posting/application",
            posting_url="",
        )
        self.assertTrue(chrome_agent_supports_job(job))
        self.assertEqual(chrome_agent_adapter(job), "ashby_hosted")
        self.assertEqual(get_submission_executor(job), EXECUTOR_CHROME_AGENT)

    def test_settings_list_ashby_as_browser_agent(self):
        self.assertRegex(
            self.settings_source,
            r"<span>Ashby</span>\s*<strong>Browser Agent</strong>",
        )

    def test_agent_uses_question_handoff_and_verification_pause(self):
        self.assertIn('"ashby_hosted"', self.source)
        self.assertIn('"needs_application_answer"', self.source)
        self.assertIn('"waiting_verification"', self.source)
        self.assertIn("Submit Application", self.source)
        self.assertNotIn("grecaptcha.execute", self.source)
        self.assertNotIn("hcaptcha.execute", self.source)

    def test_agent_targets_stable_ashby_form_contracts(self):
        self.assertIn(".ashby-application-form-container", self.source)
        self.assertIn(".ashby-application-form-field-entry", self.source)
        self.assertIn(".ashby-application-form-question-title", self.source)
        self.assertIn(".ashby-application-form-input-autocomplete", self.source)
        self.assertIn(".ashby-application-form-input-autocomplete-popup-result", self.source)
        self.assertIn(".ashby-application-form-submit-button button", self.source)
        self.assertIn(".ashby-application-form-success-container", self.source)
        self.assertIn("your application was successfully submitted", self.source)

    def test_agent_handles_profile_memory_and_structured_education(self):
        for field in (
            "first_name",
            "last_name",
            "email",
            "phone",
            "linkedin_url",
            "github_url",
            "website_url",
            "city",
            "postal_code",
            "education_school",
            "education_degree",
            "education_discipline",
            "answer_memories",
        ):
            self.assertIn(field, self.source)
        self.assertIn('return "School"', self.source)
        self.assertIn('return "Degree"', self.source)
        self.assertIn('return "Field of Study"', self.source)

    def test_agent_does_not_accept_placeholders_or_silent_checkbox_assignment(self):
        self.assertIn("placeholderChoice", self.source)
        self.assertIn("if (!radio.checked) radio.click()", self.source)
        self.assertIn("if (box.checked !== shouldCheck) box.click()", self.source)
        self.assertNotIn("radio.checked = true", self.source)
        self.assertNotIn("box.checked = shouldCheck", self.source)

    def test_agent_only_pauses_for_a_visible_interactive_challenge(self):
        self.assertIn('iframe[src*=\"recaptcha\" i][title*=\"challenge\" i]', self.source)
        self.assertIn("intersectsViewport", self.source)
        self.assertIn("captchaVisible && !verificationReported", self.source)
        self.assertNotIn('iframe[src*=\"recaptcha\"],', self.source)

class AshbyAgentSyntaxTests(unittest.TestCase):
    def test_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent syntax tests.")
        subprocess.run([node, "--check", str(AGENT_PATH)], check=True, capture_output=True, text=True)

if __name__ == "__main__":
    unittest.main()
