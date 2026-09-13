import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AGENT_PATH = (
    ROOT
    / "browser_extensions"
    / "jobfinitum_chrome_agent"
    / "lever_agent.js"
)
EDGE_CASE_PATH = (
    ROOT
    / "tests"
    / "js"
    / "lever_agent_edge_cases.mjs"
)


def node_executable():
    installed = shutil.which("node")
    if installed:
        return installed

    bundled = (
        ROOT
        / "venv"
        / "Lib"
        / "site-packages"
        / "playwright"
        / "driver"
        / "node.exe"
    )
    return str(bundled) if bundled.exists() else None


class LeverAgentSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = AGENT_PATH.read_text(encoding="utf-8")

    def test_agent_verifies_values_after_react_updates(self):
        self.assertIn("waitForLeverValue", self.source)
        self.assertIn("currentLeverControl", self.source)
        self.assertIn("unpersistedLeverAnswers", self.source)
        self.assertIn(
            "await applySavedLeverAnswers(task)",
            self.source,
        )
        self.assertIn(
            "await applyReusableLeverAnswers(task)",
            self.source,
        )

    def test_agent_uses_real_clicks_for_choices(self):
        self.assertIn("radio.click()", self.source)
        self.assertIn("box.click()", self.source)
        self.assertNotIn("radio.checked = true", self.source)
        self.assertNotIn("box.checked = shouldCheck", self.source)

    def test_uncommitted_fields_return_to_application_answers(self):
        self.assertIn(
            '"needs_application_answer"',
            self.source,
        )
        self.assertIn(
            "uncommitted_fields",
            self.source,
        )


class LeverAgentScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = node_executable()
        if not cls.node:
            raise unittest.SkipTest(
                "Node.js is required for Chrome Agent tests."
            )

    def test_javascript_syntax(self):
        subprocess.run(
            [self.node, "--check", str(AGENT_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_react_field_persistence_edge_cases(self):
        subprocess.run(
            [self.node, str(EDGE_CASE_PATH)],
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()

