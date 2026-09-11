import os
import unittest


os.environ["JOB_SCHEDULER_ENABLED"] = "false"
os.environ["JOB_LIFECYCLE_ENABLED"] = "false"

from app import app
from routes import (
    duplicate_route_rules,
    format_route_catalog,
    registered_routes,
)


class RouteCatalogTests(unittest.TestCase):
    def test_live_routes_have_no_method_overlap(self):
        self.assertEqual(
            duplicate_route_rules(app),
            {},
        )

    def test_catalog_covers_current_application_surface(self):
        routes = registered_routes(app)
        rules = {route.rule for route in routes}

        self.assertGreaterEqual(len(routes), 90)
        self.assertIn("/", rules)
        self.assertIn("/admin/job-sources", rules)
        self.assertIn("/auto-apply", rules)
        self.assertIn(
            "/api/chrome-agent/task/<token>",
            rules,
        )
        self.assertIn("/jobs", rules)
        self.assertIn("/resumes/upload", rules)

        catalog = format_route_catalog(app)
        self.assertIn(
            "Overlapping route registrations: none",
            catalog,
        )
        self.assertIn(
            f"Total routes: {len(routes)}",
            catalog,
        )


if __name__ == "__main__":
    unittest.main()
