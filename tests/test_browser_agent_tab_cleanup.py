import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKGROUND_PATH = (
    ROOT
    / "browser_extensions"
    / "jobfinitum_chrome_agent"
    / "background.js"
)
SITE_SCRIPT_PATH = ROOT / "static" / "js" / "chrome_agent_site.js"


class BrowserAgentTabCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.background = BACKGROUND_PATH.read_text(encoding="utf-8")
        cls.site_script = SITE_SCRIPT_PATH.read_text(encoding="utf-8")

    def test_resolved_target_is_not_launched_a_second_time(self):
        start = self.site_script.index(
            "result.status\n        === RESOLVED_APPLICATION_STATUS"
        )
        end = self.site_script.index(
            "result.status\n        === AGENT_RUNNING_STATUS",
            start,
        )
        resolved_block = self.site_script[start:end]

        self.assertNotIn("submitCandidate(", resolved_block)
        self.assertIn("scheduleBatchWatchdog(state)", resolved_block)

    def test_terminal_results_have_a_background_cleanup_backstop(self):
        expected_statuses = {
            "submitted",
            "needs_application_answer",
            "needs_user_action",
            "unsupported",
            "failed",
            "posting_closed",
            "needs_manual_destination",
        }
        for status in expected_statuses:
            self.assertIn(f'"{status}"', self.background)

        self.assertIn(
            "cleanupTerminalAgentTab(",
            self.background,
        )
        self.assertIn(
            'waitingUrl.searchParams.set(\n      "batch_wait",\n      "1"',
            self.background,
        )


if __name__ == "__main__":
    unittest.main()
