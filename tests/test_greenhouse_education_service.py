import unittest
from unittest.mock import Mock, patch

from services.greenhouse_education_service import (
    GreenhouseEducationLookupError,
    _cached_school_search,
    search_greenhouse_schools,
)


class GreenhouseEducationServiceTests(unittest.TestCase):
    def setUp(self):
        _cached_school_search.cache_clear()

    @patch("services.greenhouse_education_service.requests.get")
    def test_search_returns_deduplicated_greenhouse_schools(self, get):
        response = Mock()
        response.json.return_value = {
            "items": [
                {"id": 1, "text": "Georgia State University"},
                {"id": 2, "text": "Georgia Tech"},
                {"id": 3, "text": "georgia state university"},
            ]
        }
        get.return_value = response

        schools = search_greenhouse_schools(
            "  Geo  ",
            board_tokens=["example-board"],
        )

        self.assertEqual(
            [school["label"] for school in schools],
            ["Georgia State University", "Georgia Tech"],
        )
        get.assert_called_once()
        self.assertEqual(
            get.call_args.kwargs["params"]["term"],
            "geo",
        )

    def test_search_requires_three_characters(self):
        with self.assertRaisesRegex(ValueError, "at least 3"):
            search_greenhouse_schools("GT")

    @patch("services.greenhouse_education_service.requests.get")
    def test_search_falls_back_when_preferred_board_fails(self, get):
        failed_response = Mock()
        failed_response.raise_for_status.side_effect = (
            __import__("requests").HTTPError("not found")
        )
        fallback_response = Mock()
        fallback_response.json.return_value = {
            "items": [
                {"id": 9, "text": "Harvard University"},
            ]
        }
        get.side_effect = [
            failed_response,
            fallback_response,
        ]

        schools = search_greenhouse_schools(
            "Har",
            board_tokens=["retired-board"],
        )

        self.assertEqual(
            schools[0]["label"],
            "Harvard University",
        )
        self.assertEqual(get.call_count, 2)

    @patch("services.greenhouse_education_service.requests.get")
    def test_search_reports_catalog_outage(self, get):
        get.side_effect = __import__("requests").ConnectionError(
            "offline"
        )

        with self.assertRaises(GreenhouseEducationLookupError):
            search_greenhouse_schools(
                "Geo",
                board_tokens=["example-board"],
            )


if __name__ == "__main__":
    unittest.main()
