import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from models import ApplicationHostClassification, db
from services.auto_apply_submission import chrome_agent_service
from services.auto_apply_submission.chrome_agent_service import (
    apply_cached_host_manual_handoff,
    chrome_agent_adapter,
    chrome_agent_supports_job,
)
from services.auto_apply_submission.host_classification_service import (
    NO_SUPPORTED_ATS,
    SUPPORTED_WRAPPER,
    UNSUPPORTED_DESTINATION,
    host_scan_decision,
    lookup_host_classification,
    normalize_application_hostname,
    remember_host_classification,
)


class ApplicationHostClassificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            TESTING=True,
        )
        db.init_app(cls.app)
        cls.context = cls.app.app_context()
        cls.context.push()
        ApplicationHostClassification.__table__.create(
            bind=db.engine,
            checkfirst=True,
        )

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        cls.context.pop()

    def setUp(self):
        ApplicationHostClassification.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.rollback()

    @staticmethod
    def job(url, *, posting_url=None):
        return SimpleNamespace(
            apply_url=url,
            posting_url=posting_url or url,
            company_name="Example",
        )

    def test_hostname_normalization_combines_www_variants(self):
        self.assertEqual(
            normalize_application_hostname(
                "https://WWW.Example.com.:443/jobs/123"
            ),
            "example.com",
        )
        self.assertEqual(normalize_application_hostname("not a url"), "")

    def test_negative_classification_blocks_only_until_expiration(self):
        observed_at = datetime(2026, 9, 11, 12, 0, 0)
        target = "https://careers.example.com/jobs/123"
        remember_host_classification(
            target,
            NO_SUPPORTED_ATS,
            evidence_kind="resolver_no_target",
            now=observed_at,
        )
        db.session.flush()

        self.assertFalse(
            host_scan_decision(target, now=observed_at)
        )
        self.assertIsNone(
            host_scan_decision(
                target,
                now=observed_at + timedelta(hours=25),
            )
        )

    def test_confirmed_wrapper_replaces_negative_and_resists_weak_downgrade(self):
        observed_at = datetime(2026, 9, 11, 12, 0, 0)
        target = "https://careers.example.com/jobs/123"
        remember_host_classification(
            target,
            NO_SUPPORTED_ATS,
            now=observed_at,
        )
        remember_host_classification(
            target,
            SUPPORTED_WRAPPER,
            adapter_name="greenhouse_hosted",
            evidence_kind="resolved_hosted_ats",
            now=observed_at + timedelta(minutes=1),
        )
        remember_host_classification(
            target,
            NO_SUPPORTED_ATS,
            now=observed_at + timedelta(minutes=2),
        )
        db.session.flush()

        record = lookup_host_classification(target)
        self.assertEqual(record.classification, SUPPORTED_WRAPPER)
        self.assertEqual(record.adapter_name, "greenhouse_hosted")
        self.assertTrue(
            host_scan_decision(
                target,
                now=observed_at + timedelta(minutes=3),
            )
        )

    def test_cache_changes_wrapper_routing_without_hiding_explicit_evidence(self):
        target = "https://careers.example.com/jobs/platform-engineer"
        middleman = (
            "https://himalayas.app/companies/example/"
            "jobs/platform-engineer"
        )
        remember_host_classification(target, NO_SUPPORTED_ATS)
        db.session.flush()

        cached_job = self.job(target, posting_url=middleman)
        self.assertFalse(chrome_agent_supports_job(cached_job))
        with self.assertRaises(ValueError):
            chrome_agent_adapter(cached_job)

        explicit_job = self.job(
            f"{target}?gh_jid=123456",
            posting_url=middleman,
        )
        self.assertTrue(chrome_agent_supports_job(explicit_job))
        self.assertEqual(
            chrome_agent_adapter(explicit_job),
            "employer_site_resolver",
        )

    def test_positive_cache_allows_direct_employer_job_scan(self):
        target = "https://careers.example.com/jobs/platform-engineer"
        remember_host_classification(
            target,
            SUPPORTED_WRAPPER,
            adapter_name="lever_hosted",
        )
        db.session.flush()

        direct_job = self.job(target)
        self.assertTrue(chrome_agent_supports_job(direct_job))
        self.assertEqual(
            chrome_agent_adapter(direct_job),
            "employer_site_resolver",
        )

    def test_cached_negative_creates_manual_handoff_without_browser_launch(self):
        target = "https://careers.example.com/jobs/platform-engineer"
        remember_host_classification(
            target,
            UNSUPPORTED_DESTINATION,
        )
        db.session.flush()
        candidate = SimpleNamespace(
            status="Pending Review",
            reviewed_at=None,
            discovered_job=self.job(target),
        )
        result = {"status": "Unsupported", "manual_application": True}

        with (
            patch.object(
                chrome_agent_service,
                "get_or_create_application",
                return_value=SimpleNamespace(),
            ),
            patch.object(
                chrome_agent_service,
                "get_or_create_package",
                return_value=SimpleNamespace(),
            ),
            patch.object(
                chrome_agent_service,
                "_record_resolver_manual_handoff",
                return_value=result,
            ) as manual_handoff,
        ):
            actual = apply_cached_host_manual_handoff(
                candidate,
                SimpleNamespace(id=1),
            )

        self.assertEqual(actual, result)
        self.assertEqual(candidate.status, "Approved")
        self.assertEqual(
            manual_handoff.call_args.kwargs["adapter_name"],
            "employer_site_cache",
        )
        self.assertTrue(
            manual_handoff.call_args.kwargs["detail"]["cache_hit"]
        )


if __name__ == "__main__":
    unittest.main()
