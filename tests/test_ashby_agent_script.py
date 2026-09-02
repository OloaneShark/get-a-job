import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = ROOT / "browser_extensions" / "jobfinitum_chrome_agent" / "ashby_agent.js"
MANIFEST_PATH = ROOT / "browser_extensions" / "jobfinitum_chrome_agent" / "manifest.json"

class AshbyAgentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    def test_manifest_registers_ashby(self):
        self.assertEqual(self.manifest["version"], "0.5.0")
        self.assertIn("https://jobs.ashbyhq.com/*", self.manifest["host_permissions"])
        self.assertTrue(any(
            "https://jobs.ashbyhq.com/*" in script.get("matches", [])
            and "ashby_agent.js" in script.get("js", [])
            for script in self.manifest["content_scripts"]
        ))

    def test_agent_uses_question_handoff_and_verification_pause(self):
        self.assertIn('"ashby_hosted"', self.source)
        self.assertIn('"needs_application_answer"', self.source)
        self.assertIn('"waiting_verification"', self.source)
        self.assertIn("Submit Application", self.source)
        self.assertNotIn("grecaptcha.execute", self.source)
        self.assertNotIn("hcaptcha.execute", self.source)

class AshbyAgentSyntaxTests(unittest.TestCase):
    def test_javascript_syntax(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("Node.js is required for Chrome Agent syntax tests.")
        subprocess.run([node, "--check", str(AGENT_PATH)], check=True, capture_output=True, text=True)

if __name__ == "__main__":
    unittest.main()
