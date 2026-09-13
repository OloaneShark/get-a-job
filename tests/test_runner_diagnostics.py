import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["JOB_SCHEDULER_ENABLED"] = "false"
os.environ["JOB_LIFECYCLE_ENABLED"] = "false"

from flask import Flask

from models import ApplicationSubmissionAttempt, db
from services.auto_apply_submission import chrome_agent_service as service
from services.auto_apply_submission.runner_diagnostics import (
    REASONS, attempt_diagnostics, diagnostic_run_id, normalize_diagnostics,
    safe_url, update_receipt,
)


class RunnerDiagnosticTests(unittest.TestCase):
    def test_every_result_has_a_reason_and_unknown_observations(self):
        for status in REASONS:
            with self.subTest(status=status):
                result = normalize_diagnostics(status, {"diagnostics": {"batch": True}})
                self.assertNotEqual(result["reason_code"], "unknown_result")
                self.assertEqual(result["tab_outcome"], "not_reported")
                self.assertEqual(result["batch_outcome"], "not_reported")

    def test_specific_evidence_and_timing_are_preserved(self):
        result = normalize_diagnostics("needs_application_answer", {
            "uncommitted_fields": ["Degree", "Nationality", "Degree"],
            "diagnostics": {"elapsed_ms": 12345, "retry_count": 2},
        })
        self.assertEqual(result["reason_code"], "field_not_persisted")
        self.assertEqual(result["failed_fields"], ["Degree", "Nationality"])
        self.assertEqual(result["elapsed_ms"], 12345)
        self.assertEqual(result["retry_count"], 2)

    def test_timeout_records_the_last_known_stage(self):
        result = normalize_diagnostics("needs_user_action", {
            "reason": "batch_result_timeout",
            "diagnostics": {"phase": "resume_upload"},
        })
        self.assertEqual(result["reason_code"], "runner_timeout")
        self.assertEqual(result["phase"], "resume_upload")

    def test_submission_timeout_is_not_a_resolver_timeout(self):
        result = normalize_diagnostics("unsupported", {"reason": "submission_confirmation_timeout"})
        self.assertEqual(result["reason_code"], "submission_unconfirmed")

    def test_diagnostics_do_not_contain_answers_or_launch_credentials(self):
        result = normalize_diagnostics("failed", {
            "url": "https://user:password@example.com/job?gh_jid=42&token=secret&email=person#jobfinitum_agent=private",
            "answers": {"nationality": "private answer"},
            "diagnostics": {"token": "secret", "elapsed_ms": "invalid", "retry_count": -5},
        })
        self.assertEqual(result["url"], "https://example.com/job?gh_jid=42")
        self.assertIsNone(result["elapsed_ms"])
        self.assertEqual(result["retry_count"], 0)
        self.assertNotIn("private", json.dumps(result))
        self.assertNotIn("secret", json.dumps(result))
        self.assertEqual(safe_url("javascript:alert(1)"), "")
        self.assertEqual(safe_url("https://example.com:invalid/job"), "")
        resolved = normalize_diagnostics("resolved_application_target", {
            "resolved_url": "https://jobs.ashbyhq.com/example/role?jobId=42&token=secret",
        })
        self.assertEqual(resolved["url"], "https://jobs.ashbyhq.com/example/role?jobId=42")

    def test_legacy_and_malformed_details_render_without_claiming_observations(self):
        for raw in ("bad json", "[]", "null", None):
            with self.subTest(raw=raw):
                result = attempt_diagnostics(SimpleNamespace(
                    detail_json=raw, status="Failed", adapter_name="lever_chrome_agent", message="Failed",
                ))
                self.assertEqual(result["tab_outcome"], "not_reported")
                self.assertIsNone(result["elapsed_ms"])


class RunnerDiagnosticStorageTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.addCleanup(self.context.pop)
        self.addCleanup(db.engine.dispose)
        self.addCleanup(db.session.remove)
        self.user = SimpleNamespace(id=1)
        self.candidate = SimpleNamespace(
            id=10, status="Approved", execution_status="Not Started",
            discovered_job=SimpleNamespace(
                apply_url="https://jobs.lever.co/example/role/apply",
                posting_url="https://jobs.lever.co/example/role", company_name="Example",
            ),
        )
        self.application = SimpleNamespace(id=20)
        self.package = SimpleNamespace(id=30, answers_json=None)
        self.prepared = {
            "ok": True, "application": self.application, "package": self.package,
            "identity": SimpleNamespace(),
        }

    def test_hosted_report_persists_diagnostics_and_scoped_receipts(self):
        with patch.object(service, "prepare_chrome_agent_candidate", return_value=self.prepared):
            result = service.apply_chrome_agent_result(self.candidate, self.user, {
                "status": "needs_user_action", "message": "Could not confirm submission.",
                "detail": {"diagnostics": {"run_id": "test-run", "elapsed_ms": 12000, "batch": True}},
            })
        attempt = db.session.get(ApplicationSubmissionAttempt, result["attempt_id"])
        self.assertEqual(attempt_diagnostics(attempt)["reason_code"], "submission_unconfirmed")
        with self.assertRaises(ValueError):
            update_receipt(attempt, {"run_id": "different-run", "tab_outcome": "closed"})
        update_receipt(attempt, {"run_id": "test-run", "tab_outcome": "recycled", "status": "Submitted"})
        update_receipt(attempt, {"run_id": "test-run", "batch_outcome": "advanced"})
        db.session.commit()
        db.session.expire_all()
        saved = db.session.get(ApplicationSubmissionAttempt, result["attempt_id"])
        self.assertEqual(saved.status, "Needs User Action")
        self.assertEqual(attempt_diagnostics(saved)["tab_outcome"], "recycled")
        self.assertEqual(attempt_diagnostics(saved)["batch_outcome"], "advanced")

    def test_transition_history_does_not_change_execution_status(self):
        for status in ("Retrying With Saved Answers", "Resolved Application Target"):
            result = service._record_runner_transition(
                self.candidate, self.user, self.application, self.package,
                {"status": status, "message": status},
                {"diagnostics": {"run_id": "one-run", "retry_count": 1}}, "lever_hosted",
            )
            self.assertIsNotNone(result["attempt_id"])
        self.assertEqual(ApplicationSubmissionAttempt.query.count(), 2)
        self.assertEqual(self.candidate.execution_status, "Not Started")

    def test_receipt_routes_reject_other_users_and_other_launches(self):
        import app as web
        self.app.add_url_rule(
            "/receipt/<int:candidate_id>", view_func=web.auto_apply_diagnostic_receipt.__wrapped__, methods=["POST"],
        )
        self.app.add_url_rule("/agent/<token>", view_func=web.chrome_agent_result_api, methods=["POST"])
        run_id = diagnostic_run_id("valid-token")
        result = service._record_runner_transition(
            self.candidate, self.user, self.application, self.package,
            {"status": "Resolved Application Target", "message": "Resolved"},
            {"diagnostics": {"run_id": run_id}}, "lever_hosted",
        )
        db.session.commit()
        payload = {"attempt_id": result["attempt_id"], "run_id": run_id, "batch_outcome": "advanced"}
        client = self.app.test_client()
        with patch.object(web, "current_user", SimpleNamespace(id=2)):
            self.assertEqual(client.post("/receipt/10", json=payload).status_code, 404)
        with patch.object(web, "current_user", self.user):
            self.assertEqual(client.post("/receipt/10", json={**payload, "attempt_id": []}).status_code, 400)
            self.assertEqual(client.post("/receipt/999", json=payload).status_code, 404)
            self.assertEqual(client.post("/receipt/10", json={**payload, "run_id": "old"}).status_code, 400)
            self.assertEqual(client.post("/receipt/10", json=payload).status_code, 200)
        with patch.object(web, "_chrome_agent_candidate_from_token", return_value=(self.candidate, self.user, None)):
            self.assertEqual(client.post("/agent/valid-token", json={"event": "runner_receipt", "attempt_id": {}}).status_code, 400)
            self.assertEqual(client.post("/agent/other-token", json={**payload, "event": "runner_receipt"}).status_code, 400)
            self.assertEqual(client.post("/agent/valid-token", json={**payload, "event": "runner_receipt"}).status_code, 200)


class RunnerDiagnosticScriptTests(unittest.TestCase):
    def test_queue_template_accepts_older_render_contexts(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "templates/auto_apply_queue.html").read_text(encoding="utf-8")
        self.assertIn("(runner_diagnostics|default({})).get(candidate.id)", source)

    def test_browser_edge_cases(self):
        root = Path(__file__).resolve().parents[1]
        node = shutil.which("node") or str(root / "venv/Lib/site-packages/playwright/driver/node.exe")
        if not Path(node).is_file():
            self.skipTest("Node is required for browser diagnostics tests.")
        for script in ("runner_diagnostics_edge_cases.mjs", "runner_queue_edge_cases.mjs"):
            with self.subTest(script=script):
                subprocess.run(
                    [node, str(root / "tests/js" / script)],
                    check=True, capture_output=True, text=True,
                )


if __name__ == "__main__":
    unittest.main()
